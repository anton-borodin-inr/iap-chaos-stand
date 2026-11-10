package dev.iapchaos.stand

import android.content.Context
import android.os.SystemClock
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull

enum class Screen { MAIN, SHOP }

data class UiState(
    val configError: String? = null,
    val screen: Screen = Screen.MAIN,
    val playerId: String = "",
    val player: PlayerDto? = null,
    val pendingTaps: Int = 0,
    val syncStatus: String = "syncing",
    val startupDone: Boolean = false,
    val spendState: String = "idle",
    val spendError: String = "",
    val purchaseState: String = "idle",
    val purchaseSku: String = "",
    val purchaseTransactionId: String = "",
    val purchaseError: String = "",
    val purchaseMessage: String = "",
    val catalogState: String = "loading",
    val products: List<Product> = emptyList(),
    val offerRemainingAtFetchMs: Long = 0,
    val catalogFetchedAt: Long = 0,
)

/**
 * All client logic: startup, sync, taps, spends and purchases
 * (spec/purchase-flow.md). State is touched only on the main thread.
 */
class GameController(context: Context) : Auth {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val storage = Storage(context)
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()

    private var started = false
    private lateinit var api: Api
    private var defects = Defects.NONE

    private var installId = ""
    private var token: String? = null
    private var tapQueue = 0
    private var inflight: TapBatch? = null
    private var purchaseIntent: PurchaseIntent? = null
    private var spendIntent: SpendIntent? = null

    private var snapshot: PlayerDto? = null
    private var needStartupRecovery = true
    private val pendingAcks = linkedSetOf<String>()
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private val batchMutex = Mutex()
    private val recoveryMutex = Mutex()
    private val registerMutex = Mutex()
    private var purchaseJob: Job? = null
    private var spendJob: Job? = null
    private var lastPurchaseErrorAlreadyPurchased = false

    private val me: String? get() = tokenPlayerId(token)

    // --- Startup -------------------------------------------------------------

    fun start(extras: LaunchConfig?) {
        if (started) return
        started = true
        scope.launch { initialize(extras) }
    }

    private suspend fun initialize(extras: LaunchConfig?) {
        val loaded = storage.load()
        val config = extras ?: loaded.config ?: LaunchConfig.DEFAULT
        if (extras != null) storage.saveConfig(extras)
        val parsed = Defects.parse(config.defects)
        if (parsed.isFailure || !validateBackendUrl(config.backendUrl)) {
            val message = parsed.exceptionOrNull()?.message ?: "invalid backend_url: ${config.backendUrl}"
            _ui.update { it.copy(configError = message) }
            return
        }
        defects = parsed.getOrThrow()
        api = Api(config.backendUrl, this)
        installId = loaded.installId ?: UUID.randomUUID().toString().also { storage.saveInstallId(it) }
        token = loaded.token
        tapQueue = loaded.tapQueue
        inflight = loaded.inflight
        purchaseIntent = loaded.purchaseIntent
        storage.saveSpendIntent(null)
        publish()
        scope.launch { syncWorker() }
    }

    // --- Sync worker (spec §7) -----------------------------------------------

    private suspend fun syncWorker() {
        while (scope.isActive) {
            val ok = syncPass()
            val waitMs = when {
                !ok -> 10_000L
                tapQueue > 0 -> 2_000L
                else -> Long.MAX_VALUE
            }
            withTimeoutOrNull(waitMs) { wake.receive() }
        }
    }

    private suspend fun syncPass(): Boolean {
        setSync("syncing")
        var ok = true
        if (token == null) ok = register()
        if (ok && snapshot == null) ok = loadPlayer()
        if (ok) ok = flushTaps()
        if (ok && needStartupRecovery) {
            val result = recover()
            if (result.listed) cleanUpIntent(result.pendingIds)
            ok = result.ok
            if (ok) needStartupRecovery = false
        }
        if (ok) ok = acknowledgeOutstanding()
        if (!_ui.value.startupDone) _ui.update { it.copy(startupDone = true) }
        setSync(if (ok) "idle" else "error")
        return ok
    }

    private fun setSync(status: String) = _ui.update { it.copy(syncStatus = status) }

    fun onSyncRetry() {
        wake.trySend(Unit)
    }

    fun onBackground() {
        if (::api.isInitialized && tapQueue > 0) wake.trySend(Unit)
    }

    private suspend fun cleanUpIntent(pendingIds: Set<String>) {
        val intent = purchaseIntent ?: return
        if (intent.transactionId == null || intent.transactionId !in pendingIds) {
            purchaseIntent = null
            storage.savePurchaseIntent(null)
        }
    }

    // --- Auth ------------------------------------------------------------------

    override fun token(): String? = token

    override suspend fun reRegister(): Boolean = register()

    private suspend fun register(): Boolean = registerMutex.withLock {
        val res = api.call(
            "POST", "/players",
            decode = { WireJson.decodeFromString<RegisterResponse>(it) },
            authed = false,
            body = { WireJson.encodeToString(RegisterRequest(installId)) },
            accept = { tokenPlayerId(it.token) == it.player_id && it.player.player_id == it.player_id },
        )
        if (res !is Res.Ok) return false
        token = res.value.token
        storage.saveToken(res.value.token)
        applySnapshot(res.value.player)
        true
    }

    private suspend fun loadPlayer(): Boolean {
        val res = api.call("GET", "/player", decode = { WireJson.decodeFromString<PlayerDto>(it) },
            accept = { it.player_id == me })
        if (res is Res.Ok) applySnapshot(res.value)
        return res is Res.Ok
    }

    /** Applies a snapshot unless it is older than the one shown (spec §3). */
    private fun applySnapshot(player: PlayerDto) {
        if (player.player_id != me) return
        val current = snapshot
        if (current == null || player.version >= current.version) snapshot = player
        publish()
    }

    private fun publish() = _ui.update {
        it.copy(playerId = me ?: "", player = snapshot, pendingTaps = tapQueue)
    }

    // --- Taps (spec §8) ------------------------------------------------------------

    fun onTap() {
        if (!::api.isInitialized) return
        tapQueue += 1
        publish()
        val count = tapQueue
        scope.launch { storage.saveTapQueue(count) }
        if (tapQueue >= 50) wake.trySend(Unit)
    }

    /** Sends batches until the queue is empty. One batch in flight at a time. */
    private suspend fun flushTaps(): Boolean = batchMutex.withLock {
        while (true) {
            val batch = inflight ?: if (tapQueue > 0) {
                TapBatch(UUID.randomUUID().toString(), minOf(tapQueue, 200)).also {
                    inflight = it
                    storage.saveInflight(it)
                }
            } else {
                return@withLock true
            }
            val res = api.call(
                "POST", "/taps/sync",
                decode = { WireJson.decodeFromString<TapBatchResponse>(it) },
                body = { WireJson.encodeToString(TapBatchRequest(batch.batchId, batch.taps)) },
                accept = { it.batch_id == batch.batchId && it.taps == batch.taps && it.player.player_id == me },
            )
            when (res) {
                is Res.Ok -> {
                    finishBatch(batch)
                    applySnapshot(res.value.player)
                }
                is Res.Rejected -> {
                    if (res.status == 409) finishBatch(batch)
                    return@withLock false
                }
                Res.Unavailable -> return@withLock false
            }
        }
        @Suppress("UNREACHABLE_CODE")
        true
    }

    private suspend fun finishBatch(batch: TapBatch) {
        tapQueue = (tapQueue - batch.taps).coerceAtLeast(0)
        inflight = null
        storage.saveTapQueue(tapQueue)
        storage.saveInflight(null)
        publish()
    }

    // --- Spend (spec §9) --------------------------------------------------------------

    fun onSpend(item: String) {
        if (!_ui.value.startupDone || spendJob?.isActive == true) return
        spendIntent = SpendIntent(item, UUID.randomUUID().toString())
        runSpend()
    }

    fun onSpendRetry() {
        if (spendJob?.isActive == true || spendIntent == null) return
        runSpend()
    }

    fun onSpendDismiss() {
        if (spendJob?.isActive == true) return
        _ui.update { it.copy(spendState = "idle", spendError = "") }
    }

    private fun runSpend() {
        val intent = spendIntent ?: return
        _ui.update { it.copy(spendState = "in_progress", spendError = "") }
        spendJob = scope.launch {
            val error = withTimeoutOrNull(ACTION_DEADLINE_MS) { spendOnce(intent) } ?: "unavailable"
            if (error.isEmpty()) {
                spendIntent = null
                storage.saveSpendIntent(null)
                _ui.update { it.copy(spendState = "success", spendError = "") }
            } else {
                _ui.update { it.copy(spendState = "error", spendError = error) }
            }
        }
    }

    /** Returns "" on success, else the spend error code. */
    private suspend fun spendOnce(intent: SpendIntent): String {
        if (!flushTaps()) return "unavailable"
        storage.saveSpendIntent(intent)
        val res = api.call(
            "POST", "/spend",
            decode = { WireJson.decodeFromString<SpendResponse>(it) },
            body = { WireJson.encodeToString(SpendRequest(intent.spendId, intent.item)) },
            accept = { it.spend_id == intent.spendId && it.item == intent.item && it.player.player_id == me },
        )
        return when (res) {
            is Res.Ok -> {
                applySnapshot(res.value.player)
                ""
            }
            is Res.Rejected -> when (res.code) {
                "INSUFFICIENT_FUNDS" -> "insufficient_funds"
                "MAX_LEVEL" -> "max_level"
                else -> "rejected"
            }
            Res.Unavailable -> "unavailable"
        }
    }

    // --- Navigation and catalog ------------------------------------------------------

    fun onOpenShop() {
        if (spendJob?.isActive == true) return
        _ui.update { it.copy(screen = Screen.SHOP) }
        loadCatalog()
    }

    fun onBack() {
        if (purchaseJob?.isActive == true) return
        _ui.update { it.copy(screen = Screen.MAIN) }
        resetPurchaseUi()
    }

    fun onCatalogRetry() = loadCatalog()

    private fun loadCatalog() {
        if (!::api.isInitialized) return
        _ui.update { it.copy(catalogState = "loading") }
        scope.launch {
            val res = api.call("GET", "/catalog", decode = { WireJson.decodeFromString<Catalog>(it) },
                accept = { it.products.isNotEmpty() })
            if (res is Res.Ok) {
                val offer = res.value.products.firstNotNullOfOrNull { it.offer }
                val remaining = offer?.let {
                    Instant.parse(it.expires_at).toEpochMilli() - Instant.parse(res.value.server_time).toEpochMilli()
                } ?: 0L
                _ui.update {
                    it.copy(
                        catalogState = "ready",
                        products = res.value.products,
                        offerRemainingAtFetchMs = remaining,
                        catalogFetchedAt = SystemClock.elapsedRealtime(),
                    )
                }
            } else {
                _ui.update { it.copy(catalogState = "error") }
            }
        }
    }

    // --- Purchase (spec §5) -----------------------------------------------------------

    private enum class Phase { STORE, VALIDATE, RECOVERY }

    private sealed interface Outcome {
        data class Success(val transactionId: String) : Outcome
        data class Failure(val code: String, val transactionId: String? = null) : Outcome
    }

    fun onBuy(sku: String) {
        val s = _ui.value
        if (!s.startupDone || s.purchaseState != "idle" || purchaseJob?.isActive == true) return
        val intent = PurchaseIntent(sku, UUID.randomUUID().toString())
        purchaseIntent = intent
        lastPurchaseErrorAlreadyPurchased = false
        runPurchase(intent, Phase.STORE)
    }

    fun onPurchaseRetry() {
        if (purchaseJob?.isActive == true || _ui.value.purchaseState != "error") return
        val sku = _ui.value.purchaseSku
        val intent = purchaseIntent
        when {
            lastPurchaseErrorAlreadyPurchased || intent == null ->
                runPurchase(PurchaseIntent(sku, ""), Phase.RECOVERY)
            intent.transactionId != null -> runPurchase(intent, Phase.VALIDATE)
            else -> runPurchase(intent, Phase.STORE)
        }
    }

    fun onPurchaseDismiss() {
        if (purchaseJob?.isActive == true) return
        resetPurchaseUi()
    }

    private fun resetPurchaseUi() = _ui.update {
        it.copy(purchaseState = "idle", purchaseSku = "", purchaseTransactionId = "", purchaseError = "",
            purchaseMessage = "")
    }

    private fun runPurchase(intent: PurchaseIntent, start: Phase) {
        _ui.update {
            it.copy(purchaseState = "in_progress", purchaseSku = intent.sku,
                purchaseTransactionId = intent.transactionId ?: "", purchaseError = "",
                purchaseMessage = "Processing purchase…")
        }
        purchaseJob = scope.launch {
            if (start == Phase.STORE) storage.savePurchaseIntent(intent)
            val outcome = withTimeoutOrNull(ACTION_DEADLINE_MS) { purchase(intent, start) }
                ?: Outcome.Failure("unavailable", purchaseIntent?.transactionId)
            when (outcome) {
                is Outcome.Success -> {
                    lastPurchaseErrorAlreadyPurchased = false
                    _ui.update {
                        it.copy(purchaseState = "success", purchaseTransactionId = outcome.transactionId,
                            purchaseError = "", purchaseMessage = "Purchase complete.")
                    }
                    pendingAcks.add(outcome.transactionId)
                    wake.trySend(Unit)
                }
                is Outcome.Failure -> {
                    lastPurchaseErrorAlreadyPurchased = outcome.code == "already_purchased"
                    _ui.update {
                        it.copy(purchaseState = "error", purchaseTransactionId = outcome.transactionId ?: "",
                            purchaseError = outcome.code,
                            purchaseMessage = "Purchase not confirmed. A paid purchase is delivered automatically.")
                    }
                }
            }
        }
    }

    private suspend fun purchase(start: PurchaseIntent, phase: Phase): Outcome {
        var intent = start
        if (phase == Phase.RECOVERY) return recoverForSku(intent.sku)
        if (phase == Phase.STORE) {
            var key = intent.idempotencyKey
            val res = api.call(
                "POST", "/store/purchases",
                decode = { WireJson.decodeFromString<StoreTransaction>(it) },
                body = { attempt ->
                    if (defects.on("O01") && attempt > 1) key = UUID.randomUUID().toString()
                    WireJson.encodeToString(CreatePurchaseRequest(intent.sku, key))
                },
                accept = {
                    it.idempotency_key == key && it.sku == intent.sku &&
                        receiptTransactionId(it.receipt) == it.transaction_id
                },
            )
            when (res) {
                is Res.Ok -> {
                    intent = intent.copy(transactionId = res.value.transaction_id, receipt = res.value.receipt)
                    purchaseIntent = intent
                    storage.savePurchaseIntent(intent)
                    _ui.update { it.copy(purchaseTransactionId = res.value.transaction_id) }
                }
                is Res.Rejected ->
                    return if (res.code == "ALREADY_PURCHASED") recoverForSku(intent.sku)
                    else Outcome.Failure("rejected")
                Res.Unavailable -> return Outcome.Failure("unavailable")
            }
        }
        val transactionId = intent.transactionId!!
        if (defects.on("O02")) acknowledge(transactionId)
        return when (val v = validate(transactionId, intent.receipt!!)) {
            is Validation.Ok -> Outcome.Success(transactionId)
            Validation.ReceiptRejected -> Outcome.Failure("invalid_receipt", transactionId)
            is Validation.Rejected ->
                if (defects.on("O03")) Outcome.Success(transactionId)
                else Outcome.Failure("rejected", transactionId)
            Validation.Unavailable -> Outcome.Failure("unavailable", transactionId)
        }
    }

    private suspend fun recoverForSku(sku: String): Outcome {
        val result = recover()
        purchaseIntent = null
        storage.savePurchaseIntent(null)
        val granted = result.granted.firstOrNull { it.second == sku }
        return if (granted != null) Outcome.Success(granted.first) else Outcome.Failure("already_purchased")
    }

    // --- Validation, recovery and acknowledge (spec §6) --------------------------------------

    private sealed interface Validation {
        data class Ok(val response: ValidateResponse) : Validation
        data object ReceiptRejected : Validation
        data class Rejected(val code: String?) : Validation
        data object Unavailable : Validation
    }

    /** Validates a receipt; on the first receipt rejection, refetches it from the store once. */
    private suspend fun validate(transactionId: String, original: Receipt): Validation {
        var receipt = original
        var refetched = false
        while (true) {
            val sent = receipt
            val res = api.call(
                "POST", "/purchases/validate",
                decode = { WireJson.decodeFromString<ValidateResponse>(it) },
                body = { WireJson.encodeToString(ValidateRequest(sent)) },
                accept = { it.transaction_id == transactionId && it.player.player_id == me },
            )
            when (res) {
                is Res.Ok -> {
                    applySnapshot(res.value.player)
                    return Validation.Ok(res.value)
                }
                is Res.Rejected -> {
                    val receiptError = res.status == 400 &&
                        (res.code == "INVALID_SIGNATURE" || res.code == "MALFORMED_RECEIPT")
                    if (!receiptError) return Validation.Rejected(res.code)
                    if (refetched) return Validation.ReceiptRejected
                    receipt = refetch(transactionId) ?: return Validation.Unavailable
                    refetched = true
                }
                Res.Unavailable -> return Validation.Unavailable
            }
        }
    }

    private suspend fun refetch(transactionId: String): Receipt? {
        val res = api.call("GET", "/store/purchases/$transactionId",
            decode = { WireJson.decodeFromString<StoreTransaction>(it) },
            accept = { it.transaction_id == transactionId && receiptTransactionId(it.receipt) == transactionId })
        return (res as? Res.Ok)?.value?.receipt
    }

    private suspend fun acknowledge(transactionId: String): Boolean {
        val res = api.call("POST", "/store/purchases/$transactionId/acknowledge",
            decode = { WireJson.decodeFromString<StoreTransaction>(it) },
            accept = { it.transaction_id == transactionId && it.status == "acknowledged" })
        if (res is Res.Ok) {
            pendingAcks.remove(transactionId)
            if (purchaseIntent?.transactionId == transactionId) {
                purchaseIntent = null
                storage.savePurchaseIntent(null)
            }
        }
        return res is Res.Ok
    }

    private suspend fun acknowledgeOutstanding(): Boolean {
        var ok = true
        for (id in pendingAcks.toList()) if (!acknowledge(id)) ok = false
        return ok
    }

    private data class Recovery(
        val ok: Boolean,
        val listed: Boolean,
        val pendingIds: Set<String> = emptySet(),
        val granted: List<Pair<String, String>> = emptyList(),
    )

    private suspend fun recover(): Recovery = recoveryMutex.withLock {
        val list = api.call("GET", "/store/purchases?status=pending",
            decode = { WireJson.decodeFromString<StoreTransactionList>(it) },
            accept = { it.player_id == me })
        if (list !is Res.Ok) return@withLock Recovery(ok = false, listed = false)
        var ok = true
        val granted = mutableListOf<Pair<String, String>>()
        val ids = mutableSetOf<String>()
        for (tx in list.value.transactions) {
            val id = receiptTransactionId(tx.receipt) ?: tx.transaction_id
            ids.add(id)
            when (val v = validate(id, tx.receipt)) {
                is Validation.Ok -> {
                    granted.add(id to v.response.sku)
                    if (!acknowledge(id)) {
                        pendingAcks.add(id)
                        ok = false
                    }
                }
                else -> ok = false
            }
        }
        Recovery(ok = ok, listed = true, pendingIds = ids, granted = granted)
    }

    companion object {
        const val ACTION_DEADLINE_MS = 45_000L
    }
}
