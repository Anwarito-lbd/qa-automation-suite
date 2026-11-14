plugins {
    kotlin("jvm") version "2.0.21"
}

group = "com.aegispay.qa"
version = "1.0.0"

repositories {
    mavenCentral()
}

dependencies {
    implementation("io.appium:java-client:9.3.0")
    testImplementation(kotlin("test"))
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.3")
}

kotlin {
    jvmToolchain(21)
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "skipped", "failed")
    }
}
