package dev.iapchaos.stand

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import kotlinx.serialization.Serializable

private val Context.standStore by preferencesDataStore(name = "stand")

@Serializable
data class TapBatch(val batchId: String, val taps: Int)

@Serializable
data class PurchaseIntent(
    val sku: String,
    val idempotencyKey: String,
    val transactionId: String? = null,
    val receipt: Receipt? = null,
)

@Serializable
data class SpendIntent(val item: String, val spendId: String)

/** Persistent client state (spec/purchase-flow.md §4). Every write is durable when it returns. */
class Storage(context: Context) {
    private val store = context.applicationContext.standStore

    data class Loaded(
        val config: LaunchConfig?,
        val installId: String?,
        val token: String?,
        val tapQueue: Int,
        val inflight: TapBatch?,
        val purchaseIntent: PurchaseIntent?,
    )

    suspend fun load(): Loaded {
        val p = store.data.first()
        val url = p[BACKEND_URL]
        return Loaded(
            config = url?.let { LaunchConfig(it, p[DEFECTS] ?: "") },
            installId = p[INSTALL_ID],
            token = p[TOKEN],
            tapQueue = p[TAP_QUEUE] ?: 0,
            inflight = p[INFLIGHT]?.let { runCatching { WireJson.decodeFromString<TapBatch>(it) }.getOrNull() },
            purchaseIntent = p[PURCHASE_INTENT]?.let {
                runCatching { WireJson.decodeFromString<PurchaseIntent>(it) }.getOrNull()
            },
        )
    }

    suspend fun saveConfig(config: LaunchConfig) = store.edit {
        it[BACKEND_URL] = config.backendUrl
        it[DEFECTS] = config.defects
    }

    suspend fun saveInstallId(id: String) = put(INSTALL_ID, id)
    suspend fun saveToken(token: String) = put(TOKEN, token)
    suspend fun saveTapQueue(count: Int) = store.edit { it[TAP_QUEUE] = count }
    suspend fun saveInflight(batch: TapBatch?) = put(INFLIGHT, batch?.let { WireJson.encodeToString(it) })
    suspend fun savePurchaseIntent(intent: PurchaseIntent?) =
        put(PURCHASE_INTENT, intent?.let { WireJson.encodeToString(it) })
    suspend fun saveSpendIntent(intent: SpendIntent?) = put(SPEND_INTENT, intent?.let { WireJson.encodeToString(it) })

    private suspend fun put(key: Preferences.Key<String>, value: String?) = store.edit {
        if (value == null) it.remove(key) else it[key] = value
    }

    private companion object {
        val BACKEND_URL = stringPreferencesKey("backend_url")
        val DEFECTS = stringPreferencesKey("defects")
        val INSTALL_ID = stringPreferencesKey("install_id")
        val TOKEN = stringPreferencesKey("token")
        val TAP_QUEUE = intPreferencesKey("tap_queue")
        val INFLIGHT = stringPreferencesKey("inflight_batch")
        val PURCHASE_INTENT = stringPreferencesKey("purchase_intent")
        val SPEND_INTENT = stringPreferencesKey("spend_intent")
    }
}
