package dev.iapchaos.stand

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent

class StandApp : Application() {
    val controller: GameController by lazy { GameController(this) }
}

class MainActivity : ComponentActivity() {
    private val controller get() = (application as StandApp).controller

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        controller.start(launchExtras())
        setContent { StandUi(controller) }
    }

    override fun onStop() {
        super.onStop()
        controller.onBackground()
    }

    /** Launch parameters from intent extras (spec/launch.md). Null when neither extra is present. */
    private fun launchExtras(): LaunchConfig? {
        val extras = intent?.extras ?: return null
        if (!extras.containsKey(EXTRA_BACKEND_URL) && !extras.containsKey(EXTRA_DEFECTS)) return null
        return LaunchConfig(
            backendUrl = extras.getString(EXTRA_BACKEND_URL) ?: LaunchConfig.DEFAULT_BACKEND_URL,
            defects = extras.getString(EXTRA_DEFECTS) ?: "",
        )
    }

    private companion object {
        const val EXTRA_BACKEND_URL = "backend_url"
        const val EXTRA_DEFECTS = "defects"
    }
}
