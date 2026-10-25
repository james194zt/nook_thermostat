plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.neatthermostat.panelhelper"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.neatthermostat.panelhelper"
        // NSPanel Pro gen 1 runs Android 8.1, gen 2 Android 11.
        minSdk = 26
        // Sideloaded, never on the Play Store: target 30 keeps the background rules the
        // panel's Android 11 actually enforces (no foreground-service types needed).
        targetSdk = 30
        versionCode = 5
        versionName = "0.2.2"
    }

    signingConfigs {
        // A stable key in the repo's (git-ignored) keystore, so updates install over the old app.
        create("panel") {
            storeFile = file(System.getenv("NEAT_HELPER_KEYSTORE") ?: "${rootDir}/keystore/neat-panel-helper.jks")
            storePassword = System.getenv("NEAT_HELPER_KEYSTORE_PASSWORD") ?: "neat-panel-helper"
            keyAlias = "neat-panel-helper"
            keyPassword = System.getenv("NEAT_HELPER_KEYSTORE_PASSWORD") ?: "neat-panel-helper"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("panel")
        }
        debug {
            signingConfig = signingConfigs.getByName("panel")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    lint {
        // Play Store rule; this app is sideloaded onto wall panels.
        disable += "ExpiredTargetSdkVersion"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}
