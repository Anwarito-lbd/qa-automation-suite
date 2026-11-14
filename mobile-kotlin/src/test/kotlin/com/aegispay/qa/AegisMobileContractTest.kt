package com.aegispay.qa

import com.aegispay.qa.pages.LoginPage
import com.aegispay.qa.pages.WalletDashboardPage
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import io.appium.java_client.android.AndroidDriver
import io.appium.java_client.android.options.UiAutomator2Options
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.net.InetSocketAddress
import java.net.URI
import java.nio.charset.StandardCharsets
import java.util.concurrent.CopyOnWriteArrayList

class AegisMobileContractTest {

    private fun respondJson(exchange: HttpExchange, status: Int, body: String) {
        val bytes = body.toByteArray(StandardCharsets.UTF_8)
        exchange.responseHeaders.add("Content-Type", "application/json; charset=utf-8")
        exchange.sendResponseHeaders(status, bytes.size.toLong())
        exchange.responseBody.use { it.write(bytes) }
    }

    @Test
    fun `kotlin appium page objects execute W3C WebDriver login and balance sync`() {
        val events = CopyOnWriteArrayList<String>()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            val method = exchange.requestMethod
            val path = exchange.requestURI.path
            val body = exchange.requestBody.readAllBytes().toString(StandardCharsets.UTF_8)

            when {
                method == "POST" && path == "/session" -> {
                    events.add("SESSION_CREATE")
                    respondJson(
                        exchange,
                        200,
                        """{"value":{"sessionId":"kotlin-sess-1","capabilities":{"platformName":"Android","automationName":"UiAutomator2"}}}"""
                    )
                }
                method == "POST" && path.endsWith("/element") -> {
                    val elementKey = when {
                        body.contains("login-email-input") -> "el-email"
                        body.contains("input_password") -> "el-password"
                        body.contains("login-submit-btn") -> "el-submit"
                        body.contains("txt_balance") -> "el-balance"
                        body.contains("txt_orders_count") -> "el-count"
                        body.contains("dashboard-new-transfer-btn") -> "el-new-transfer"
                        else -> "el-unknown"
                    }
                    events.add("FIND:$elementKey")
                    respondJson(
                        exchange,
                        200,
                        """{"value":{"element-6066-11e4-a52e-4f735466cecf":"$elementKey"}}"""
                    )
                }
                method == "POST" && path.endsWith("/value") -> {
                    val elId = path.split("/").dropLast(1).last()
                    events.add("VALUE:$elId")
                    respondJson(exchange, 200, """{"value":null}""")
                }
                method == "POST" && path.endsWith("/click") -> {
                    val elId = path.split("/").dropLast(1).last()
                    events.add("CLICK:$elId")
                    respondJson(exchange, 200, """{"value":null}""")
                }
                method == "GET" && path.endsWith("/text") -> {
                    val elId = path.split("/").dropLast(1).last()
                    val value = if (elId == "el-balance") "$400.00" else "2"
                    respondJson(exchange, 200, """{"value":"$value"}""")
                }
                method == "DELETE" && path == "/session/kotlin-sess-1" -> {
                    events.add("SESSION_QUIT")
                    respondJson(exchange, 200, """{"value":null}""")
                }
                else -> respondJson(exchange, 404, """{"value":{"error":"unknown command"}}""")
            }
        }
        server.start()

        val options = UiAutomator2Options()
            .setDeviceName("emulator-5554")
            .setAppPackage("com.aegispay.wallet")
            .setAppActivity(".MainActivity")

        val driver = AndroidDriver(URI("http://127.0.0.1:${server.address.port}").toURL(), options)
        try {
            val loginPage = LoginPage(driver)
            val dashboard = WalletDashboardPage(driver)

            loginPage.login("kotlin.qa@aegispay.dev", "KotlinPass123!")
            assertEquals("$400.00", dashboard.readBalance())
            assertEquals(2, dashboard.readOrdersCount())
            dashboard.openNewTransfer()
        } finally {
            driver.quit()
            server.stop(0)
        }

        assertTrue(events.contains("SESSION_CREATE"))
        assertTrue(events.contains("CLICK:el-submit"))
        assertTrue(events.contains("CLICK:el-new-transfer"))
        assertTrue(events.contains("SESSION_QUIT"))
    }
}
