package dev.iapchaos.stand

import android.os.SystemClock
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay

/** UI identifiers follow spec/ui-ids.md exactly. */

@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun StandUi(controller: GameController) {
    val state by controller.ui.collectAsStateWithLifecycle()
    MaterialTheme {
        Surface(Modifier.fillMaxSize()) {
            Box(Modifier.fillMaxSize().safeDrawingPadding().semantics { testTagsAsResourceId = true }) {
                when {
                    state.configError != null -> ConfigErrorScreen(state.configError!!)
                    state.screen == Screen.MAIN -> MainScreen(state, controller)
                    else -> ShopScreen(state, controller)
                }
            }
        }
    }
}

@Composable
private fun ConfigErrorScreen(message: String) {
    Column(Modifier.fillMaxSize().padding(16.dp).testTag("screen_config_error")) {
        Text("Configuration error", style = MaterialTheme.typography.titleLarge)
        Text(message)
    }
}

@Composable
private fun TaggedText(tag: String, text: String, modifier: Modifier = Modifier) {
    // A minimum width keeps empty values in the accessibility tree (spec/ui-ids.md: elements stay present).
    Text(text, modifier.widthIn(min = 8.dp).testTag(tag))
}

private fun displayedCoins(state: UiState): String {
    val player = state.player ?: return "-"
    val taps = state.pendingTaps.toLong()
    val level = player.upgrade.level.toLong()
    val boosted = minOf(taps, player.booster.charges)
    return (player.coins + level * (taps + 2 * boosted)).toString()
}

@Composable
private fun StatusBar(state: UiState, controller: GameController) {
    Column(Modifier.fillMaxWidth().padding(bottom = 12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Coins:")
            TaggedText("coins_value", displayedCoins(state))
            Text("Crystals:")
            TaggedText("crystals_value", state.player?.crystals?.toString() ?: "-")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Sync:")
            TaggedText("sync_status", state.syncStatus)
            if (state.syncStatus == "error") {
                OutlinedButton(onClick = controller::onSyncRetry, Modifier.testTag("sync_retry")) { Text("Retry sync") }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Player:", style = MaterialTheme.typography.bodySmall)
            Text(state.playerId, Modifier.widthIn(min = 8.dp).testTag("player_id_value"), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun MainScreen(state: UiState, controller: GameController) {
    val player = state.player
    val spendBusy = state.spendState == "in_progress"
    Column(
        Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()).testTag("screen_main"),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        StatusBar(state, controller)
        Button(onClick = controller::onTap, Modifier.fillMaxWidth().height(96.dp).testTag("tap_button")) {
            Text("TAP", style = MaterialTheme.typography.headlineMedium)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Coins per tap:")
            TaggedText("tap_income_value", player?.upgrade?.tap_income?.toString() ?: "-")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Level:")
            TaggedText("upgrade_level_value", player?.upgrade?.level?.toString() ?: "-")
            Text("Next cost:")
            TaggedText("upgrade_cost_value", player?.upgrade?.next_cost?.toString() ?: "-")
        }
        Button(
            onClick = { controller.onSpend("upgrade") },
            enabled = !spendBusy && state.startupDone && (player?.upgrade?.level ?: 1) < 10,
            modifier = Modifier.testTag("upgrade_button"),
        ) { Text("Upgrade") }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Booster charges:")
            TaggedText("booster_charges_value", player?.booster?.charges?.toString() ?: "-")
            Text("Cost:")
            TaggedText("booster_cost_value", player?.booster?.cost_crystals?.toString() ?: "-")
        }
        Button(
            onClick = { controller.onSpend("booster") },
            enabled = !spendBusy && state.startupDone,
            modifier = Modifier.testTag("booster_button"),
        ) { Text("Buy booster") }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Spend:")
            TaggedText("spend_state", state.spendState)
            TaggedText("spend_error_code", state.spendError)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (state.spendState == "error") {
                OutlinedButton(onClick = controller::onSpendRetry, Modifier.testTag("spend_retry")) { Text("Retry") }
            }
            if (state.spendState == "success" || state.spendState == "error") {
                OutlinedButton(onClick = controller::onSpendDismiss, Modifier.testTag("spend_dismiss")) { Text("OK") }
            }
        }
        Spacer(Modifier.height(8.dp))
        Button(onClick = controller::onOpenShop, enabled = !spendBusy, modifier = Modifier.testTag("nav_shop")) {
            Text("Shop")
        }
    }
}

private fun formatPrice(cents: Long): String = "$" + (cents / 100) + "." + (cents % 100).toString().padStart(2, '0')

private fun formatGrant(grant: Grant): String = buildList {
    if (grant.crystals > 0) add("${grant.crystals} crystals")
    if (grant.coins > 0) add("${grant.coins} coins")
}.joinToString(" + ")

@Composable
private fun ShopScreen(state: UiState, controller: GameController) {
    var now by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    LaunchedEffect(Unit) {
        while (true) {
            now = SystemClock.elapsedRealtime()
            delay(250)
        }
    }
    val remainingMs = (state.offerRemainingAtFetchMs - (now - state.catalogFetchedAt)).coerceAtLeast(0)
    val catalogOffer = state.products.firstNotNullOfOrNull { it.offer }
    val offerPurchased = catalogOffer?.status == "purchased" || state.player?.offer?.status == "purchased"
    val offerStatus = when {
        offerPurchased -> "purchased"
        state.catalogState == "ready" && remainingMs > 0 -> "available"
        state.catalogState == "ready" -> "expired"
        else -> state.player?.offer?.status ?: "available"
    }
    val purchaseIdle = state.purchaseState == "idle"
    val terminal = state.purchaseState == "success" || state.purchaseState == "error"

    Column(
        Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()).testTag("screen_shop"),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        StatusBar(state, controller)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Purchase:")
                    TaggedText("purchase_state", state.purchaseState)
                }
                TaggedText("purchase_sku", state.purchaseSku)
                TaggedText("purchase_transaction_id", state.purchaseTransactionId)
                TaggedText("purchase_error_code", state.purchaseError)
                TaggedText("purchase_message", state.purchaseMessage)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (state.purchaseState == "error") {
                        OutlinedButton(onClick = controller::onPurchaseRetry, Modifier.testTag("purchase_retry")) {
                            Text("Retry")
                        }
                    }
                    if (terminal) {
                        OutlinedButton(onClick = controller::onPurchaseDismiss, Modifier.testTag("purchase_dismiss")) {
                            Text("OK")
                        }
                    }
                }
            }
        }
        OutlinedButton(
            onClick = controller::onBack,
            enabled = state.purchaseState != "in_progress",
            modifier = Modifier.testTag("nav_back"),
        ) { Text("Back") }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Catalog:")
            TaggedText("catalog_state", state.catalogState)
            if (state.catalogState == "error") {
                OutlinedButton(onClick = controller::onCatalogRetry, Modifier.testTag("catalog_retry")) { Text("Retry") }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Offer:")
            TaggedText("offer_status", offerStatus)
            val seconds = remainingMs / 1000
            val timer = if (offerStatus == "purchased") "" else
                "%02d:%02d".format(seconds / 60, seconds % 60)
            TaggedText("offer_timer", timer)
        }
        if (state.catalogState == "ready") {
            for (product in state.products) {
                val isOffer = product.sku == "starter_offer"
                Row(
                    Modifier.fillMaxWidth().testTag("product_${product.sku}"),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(product.title, style = MaterialTheme.typography.titleSmall)
                        TaggedText("product_${product.sku}_grant", formatGrant(product.grant))
                    }
                    TaggedText("product_${product.sku}_price", formatPrice(product.price_cents))
                    Button(
                        onClick = { controller.onBuy(product.sku) },
                        enabled = purchaseIdle && state.startupDone && (!isOffer || offerStatus == "available"),
                        modifier = Modifier.testTag("buy_${product.sku}"),
                    ) { Text("Buy") }
                }
            }
        }

    }
}
