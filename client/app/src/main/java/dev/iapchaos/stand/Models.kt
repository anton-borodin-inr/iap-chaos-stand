package dev.iapchaos.stand

import java.util.Base64
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Wire models (spec/openapi.yaml). Field names follow the JSON exactly. */

val WireJson = Json { ignoreUnknownKeys = true; explicitNulls = false }

@Serializable
data class Grant(val coins: Long, val crystals: Long)

@Serializable
data class Upgrade(val level: Int, val tap_income: Int, val next_cost: Long? = null)

@Serializable
data class Booster(val charges: Long, val cost_crystals: Long, val charges_per_purchase: Long)

@Serializable
data class OfferState(val sku: String, val expires_at: String, val status: String)

@Serializable
data class PlayerDto(
    val player_id: String,
    val coins: Long,
    val crystals: Long,
    val upgrade: Upgrade,
    val booster: Booster,
    val offer: OfferState,
    val version: Long,
    val server_time: String,
)

@Serializable
data class RegisterRequest(val install_id: String)

@Serializable
data class RegisterResponse(val player_id: String, val token: String, val player: PlayerDto)

@Serializable
data class TapBatchRequest(val batch_id: String, val taps: Int)

@Serializable
data class TapBatchResponse(
    val batch_id: String,
    val taps: Int,
    val credited_coins: Long,
    val duplicate: Boolean,
    val player: PlayerDto,
)

@Serializable
data class SpendRequest(val spend_id: String, val item: String)

@Serializable
data class SpendResponse(
    val spend_id: String,
    val item: String,
    val cost: Grant,
    val duplicate: Boolean,
    val player: PlayerDto,
)

@Serializable
data class Receipt(val payload: String, val signature: String)

@Serializable
data class ValidateRequest(val receipt: Receipt)

@Serializable
data class ValidateResponse(
    val transaction_id: String,
    val sku: String,
    val grant: Grant,
    val duplicate: Boolean,
    val player: PlayerDto,
)

@Serializable
data class CreatePurchaseRequest(val sku: String, val idempotency_key: String)

@Serializable
data class StoreTransaction(
    val transaction_id: String,
    val player_id: String,
    val sku: String,
    val quantity: Int,
    val price_cents: Long,
    val currency: String,
    val status: String,
    val idempotency_key: String,
    val created_at: String,
    val acknowledged_at: String? = null,
    val receipt: Receipt,
)

@Serializable
data class StoreTransactionList(val player_id: String, val transactions: List<StoreTransaction>)

@Serializable
data class Product(
    val sku: String,
    val title: String,
    val price_cents: Long,
    val currency: String,
    val grant: Grant,
    val one_time: Boolean,
    val offer: OfferState? = null,
)

@Serializable
data class Catalog(val server_time: String, val products: List<Product>)

@Serializable
data class ErrorBody(val code: String, val message: String = "")

@Serializable
data class ErrorEnvelope(val error: ErrorBody)

/** The canonical transaction ID: `payload.transaction_id` of the receipt, or null if it does not decode. */
fun receiptTransactionId(receipt: Receipt): String? = runCatching {
    val bytes = Base64.getUrlDecoder().decode(receipt.payload)
    WireJson.parseToJsonElement(String(bytes, Charsets.UTF_8)).jsonObject["transaction_id"]!!.jsonPrimitive.content
}.getOrNull()

/** The player ID inside a bearer token `v1.<player_id>.<mac>`. */
fun tokenPlayerId(token: String?): String? {
    val parts = token?.split(".") ?: return null
    return if (parts.size == 3 && parts[0] == "v1") parts[1] else null
}
