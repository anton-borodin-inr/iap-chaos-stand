package dev.iapchaos.stand

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Launch parameters (spec/launch.md, "Client"). */
data class LaunchConfig(val backendUrl: String, val defects: String) {
    companion object {
        const val DEFAULT_BACKEND_URL = "http://10.0.2.2:8080"
        val DEFAULT = LaunchConfig(DEFAULT_BACKEND_URL, "")
    }
}

/**
 * Defect toggles. The registry comes from defects/registry.json at build time.
 * A toggle changes behavior only; it never adds anything to traffic.
 */
class Defects private constructor(private val enabled: Set<String>) {
    fun on(id: String): Boolean = id in enabled

    companion object {
        private val ID = Regex("^[A-Z][0-9]{2}$")

        val NONE = Defects(emptySet())

        private val registry: Map<String, String> = BuildConfig.DEFECT_REGISTRY
            .split(",").filter { it.isNotBlank() }
            .associate { entry -> entry.substringBefore(":") to entry.substringAfter(":") }

        /** Returns the client defects, or an error message for an unknown ID. */
        fun parse(raw: String): Result<Defects> {
            val ids = raw.split(",").map { it.trim() }.filter { it.isNotEmpty() }
            for (id in ids) {
                if (!ID.matches(id) || id !in registry) {
                    return Result.failure(IllegalArgumentException("unknown defect id: $id"))
                }
            }
            return Result.success(Defects(ids.filter { registry[it] == "client" }.toSet()))
        }
    }
}

fun validateBackendUrl(url: String): Boolean {
    val parsed = url.toHttpUrlOrNull() ?: return false
    return parsed.encodedPath == "/" || parsed.encodedPath.isEmpty()
}
