package com.aegispay.qa.pages

import io.appium.java_client.AppiumBy
import io.appium.java_client.android.AndroidDriver
import org.openqa.selenium.By

/**
 * Kotlin Appium UIAutomator2 Page Object for AegisPay Android LoginActivity.
 */
class LoginPage(private val driver: AndroidDriver) {
    private val emailInput: By = AppiumBy.accessibilityId("login-email-input")
    private val passwordInput: By = AppiumBy.id("com.aegispay.wallet:id/input_password")
    private val submitButton: By = AppiumBy.accessibilityId("login-submit-btn")

    fun login(email: String, password: String) {
        driver.findElement(emailInput).sendKeys(email)
        driver.findElement(passwordInput).sendKeys(password)
        driver.findElement(submitButton).click()
    }
}
