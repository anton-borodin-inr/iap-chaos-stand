package dev.iapchaos.stand

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

/** Result of one call after the retry policy (spec/purchase-flow.md §2). */
sealed interface Res<out T> {
    data class Ok<T>(val value: T, val status: Int) : Res<T>
    data class Rejected(val status: Int, val code: String?) : Res<Nothing>
    data object Unavailable : Res<Nothing>
}

interface Auth {
    fun token(): String?

    /** Re-register with the stored install_id. Returns true if a new token was stored. */
    suspend fun reRegister(): Boolean
}

class Api(private val baseUrl: String, private val auth: Auth) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .callTimeout(6, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .build()

    /**
     * Sends one call with up to 3 attempts. [body] builds the JSON body for an
     * attempt. [accept] applies the response acceptance rules; a 2xx that fails
     * them counts as an invalid response and is retried.
     */
    suspend fun <T> call(
        method: String,
        path: String,
        decode: (String) -> T,
        authed: Boolean = true,
        body: ((attempt: Int) -> String)? = null,
        accept: (T) -> Boolean = { true },
    ): Res<T> {
        var reauthenticated = false
        var attempt = 1
        while (attempt <= ATTEMPTS) {
            val outcome = try {
                execute(method, path, authed, body?.invoke(attempt))
            } catch (e: IOException) {
                null
            }
            if (outcome != null) {
                val (status, text) = outcome
                when {
                    status in 200..299 -> {
                        val value = runCatching { decode(text) }.getOrNull()
                        if (value != null && runCatching { accept(value) }.getOrDefault(false)) {
                            return Res.Ok(value, status)
                        }
                    }
                    status == 401 && authed -> {
                        if (reauthenticated || !auth.reRegister()) return Res.Rejected(401, errorCode(text))
                        reauthenticated = true
                        continue
                    }
                    status == 408 || status == 429 || status >= 500 -> Unit
                    else -> return Res.Rejected(status, errorCode(text))
                }
            }
            if (attempt < ATTEMPTS) delay(BACKOFF_MS[attempt - 1])
            attempt++
        }
        return Res.Unavailable
    }

    private suspend fun execute(method: String, path: String, authed: Boolean, json: String?): Pair<Int, String> {
        val builder = Request.Builder().url(baseUrl.trimEnd('/') + path)
        if (authed) auth.token()?.let { builder.header("Authorization", "Bearer $it") }
        val requestBody = json?.toRequestBody(JSON) ?: if (method == "POST") "".toRequestBody(JSON) else null
        builder.method(method, requestBody)
        val call = http.newCall(builder.build())
        return suspendCancellableCoroutine { cont ->
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (cont.isActive) cont.resumeWithException(e)
                }

                override fun onResponse(call: Call, response: Response) {
                    try {
                        val text = response.use { it.body.string() }
                        if (cont.isActive) cont.resume(response.code to text)
                    } catch (e: IOException) {
                        if (cont.isActive) cont.resumeWithException(e)
                    }
                }
            })
        }
    }

    private fun errorCode(text: String): String? =
        runCatching { WireJson.decodeFromString<ErrorEnvelope>(text).error.code }.getOrNull()

    companion object {
        const val ATTEMPTS = 3
        val BACKOFF_MS = longArrayOf(1_000, 2_000)
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}
