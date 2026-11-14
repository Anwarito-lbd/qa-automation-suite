package com.aegispay.qa.pages

import io.appium.java_client.AppiumBy
import io.appium.java_client.android.AndroidDriver
import org.openqa.selenium.By

/**
 * Kotlin Appium UIAutomator2 Page Object for AegisPay WalletDashboardActivity.
 */
class WalletDashboardPage(private val driver: AndroidDriver) {
    private val balanceValue: By = AppiumBy.id("com.aegispay.wallet:id/txt_balance")
    private val ordersCount: By = AppiumBy.id("com.aegispay.wallet:id/txt_orders_count")
    private val newTransferButton: By = AppiumBy.accessibilityId("dashboard-new-transfer-btn")

    fun readBalance(): String = driver.findElement(balanceValue).text

    fun readOrdersCount(): Int = driver.findElement(ordersCount).text.toInt()

    fun openNewTransfer() {
        driver.findElement(newTransferButton).click()
    }
}
