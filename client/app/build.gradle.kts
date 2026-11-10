import groovy.json.JsonSlurper

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// The defect registry is shared with the server: defects/registry.json.
@Suppress("UNCHECKED_CAST")
val defectRegistry: String = (JsonSlurper().parse(rootProject.file("../defects/registry.json")) as Map<String, String>)
    .entries.joinToString(",") { "${it.key}:${it.value}" }

android {
    namespace = "dev.iapchaos.stand"
    compileSdk = 37

    defaultConfig {
        applicationId = "dev.iapchaos.stand"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "stand-v1"
        buildConfigField("String", "DEFECT_REGISTRY", "\"$defectRegistry\"")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.datastore:datastore-preferences:1.3.0")
    implementation("com.squareup.okhttp3:okhttp:5.5.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
}
