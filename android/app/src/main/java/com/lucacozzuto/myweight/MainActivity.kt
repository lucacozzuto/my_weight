package com.lucacozzuto.myweight

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var rootLayout: FrameLayout
    private lateinit var dashboardWebView: WebView
    private lateinit var loginWebView: WebView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var progressBar: ProgressBar
    private lateinit var loginPromptLayout: LinearLayout
    private lateinit var statusText: TextView

    companion object {
        private const val GARMIN_SSO_URL =
            "https://sso.garmin.com/portal/sso/en-US/sign-in?clientId=GarminConnect&service=https%3A%2F%2Fconnect.garmin.com%2Fapp"
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        rootLayout = FrameLayout(this).apply {
            setBackgroundColor(0xFF020617.toInt())
            fitsSystemWindows = true
        }

        androidx.core.view.ViewCompat.setOnApplyWindowInsetsListener(rootLayout) { view, insets ->
            val statusBarInsets = insets.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, statusBarInsets.top, 0, statusBarInsets.bottom)
            insets
        }

        setupDashboardWebView()
        setupLoginPrompt()
        setupLoginWebView()

        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = 100
            visibility = View.GONE
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                8,
                Gravity.TOP
            )
        }

        rootLayout.addView(progressBar)
        setContentView(rootLayout)

        setupBackNavigation()

        checkAuthStateAndInit()
    }

    private fun setupDashboardWebView() {
        swipeRefresh = SwipeRefreshLayout(this).apply {
            setColorSchemeColors(0xFF6366F1.toInt(), 0xFF10B981.toInt())
            setProgressBackgroundColorSchemeColor(0xFF1E293B.toInt())
        }

        dashboardWebView = WebView(this).apply {
            setBackgroundColor(0xFF020617.toInt())
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        val settings = dashboardWebView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.allowFileAccess = true

        dashboardWebView.addJavascriptInterface(WebAppInterface(), "Android")

        dashboardWebView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                swipeRefresh.isRefreshing = false
                pushCachedDataToDashboard()
            }
        }

        swipeRefresh.addView(dashboardWebView)
        rootLayout.addView(swipeRefresh)

        swipeRefresh.setOnRefreshListener {
            syncGarminData()
        }
    }

    private fun setupLoginPrompt() {
        loginPromptLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(48, 48, 48, 48)
            setBackgroundColor(0xFF020617.toInt())
            visibility = View.GONE
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        val title = TextView(this).apply {
            text = "My Weight"
            textSize = 28f
            setTextColor(0xFFFFFFFF.toInt())
            gravity = Gravity.CENTER
            paint.isFakeBoldText = true
        }

        val subtitle = TextView(this).apply {
            text = "Accedi con il tuo account Garmin Connect per visualizzare e analizzare la tua cronologia pesate"
            textSize = 14f
            setTextColor(0xFF94A3B8.toInt())
            gravity = Gravity.CENTER
            setPadding(0, 16, 0, 48)
        }

        val loginBtn = Button(this).apply {
            text = "Accedi con Garmin"
            setTextColor(0xFFFFFFFF.toInt())
            setBackgroundColor(0xFF4F46E5.toInt())
            setPadding(32, 24, 32, 24)
            setOnClickListener {
                startGarminWebLogin()
            }
        }

        statusText = TextView(this).apply {
            text = ""
            textSize = 12f
            setTextColor(0xFF38BDF8.toInt())
            gravity = Gravity.CENTER
            setPadding(0, 24, 0, 0)
        }

        loginPromptLayout.addView(title)
        loginPromptLayout.addView(subtitle)
        loginPromptLayout.addView(loginBtn)
        loginPromptLayout.addView(statusText)

        rootLayout.addView(loginPromptLayout)
    }

    private fun setupLoginWebView() {
        loginWebView = WebView(this).apply {
            setBackgroundColor(0xFF020617.toInt())
            visibility = View.GONE
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        val settings = loginWebView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.setSupportZoom(true)
        settings.builtInZoomControls = true
        settings.displayZoomControls = false
        settings.userAgentString =
            "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"

        loginWebView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                if (loginWebView.visibility == View.VISIBLE) {
                    progressBar.visibility = if (newProgress < 100) View.VISIBLE else View.GONE
                    progressBar.progress = newProgress
                }
            }
        }

        loginWebView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url?.toString() ?: ""
                return handleAuthIntercept(url)
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                if (url != null && handleAuthIntercept(url)) {
                    view?.stopLoading()
                }
            }
        }

        rootLayout.addView(loginWebView)
    }

    private fun handleAuthIntercept(url: String): Boolean {
        // Ticket intercept in redirect url (e.g. https://connect.garmin.com/app?ticket=ST-XXXXX)
        if (url.contains("ticket=")) {
            try {
                val uri = Uri.parse(url)
                val ticket = uri.getQueryParameter("ticket")
                if (!ticket.isNullOrBlank()) {
                    onTicketReceived(ticket)
                    return true
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }

        // Cookie intercept (JWT_WEB)
        val cookies = CookieManager.getInstance().getCookie(url) ?: ""
        if (cookies.contains("JWT_WEB=")) {
            val parts = cookies.split(";")
            var jwt: String? = null
            for (p in parts) {
                val kv = p.trim().split("=")
                if (kv.size == 2 && kv[0] == "JWT_WEB") {
                    jwt = kv[1]
                    break
                }
            }
            if (jwt != null) {
                GarminAuthManager.saveTokens(this, null, null, null, jwt, null)
                lifecycleScope.launch {
                    loginWebView.visibility = View.GONE
                    loginPromptLayout.visibility = View.GONE
                    swipeRefresh.visibility = View.VISIBLE
                    if (dashboardWebView.url == null || !dashboardWebView.url!!.contains("dashboard.html")) {
                        dashboardWebView.loadUrl("file:///android_asset/dashboard.html")
                    }
                    syncGarminData()
                }
                return true
            }
        }
        return false
    }

    private fun onTicketReceived(ticket: String) {
        loginWebView.visibility = View.GONE
        loginPromptLayout.visibility = View.VISIBLE
        statusText.text = "Autenticazione in corso..."
        progressBar.visibility = View.VISIBLE

        lifecycleScope.launch {
            val ok = GarminDataFetcher.exchangeTicketForToken(this@MainActivity, ticket)
            if (ok || GarminAuthManager.hasValidAuth(this@MainActivity)) {
                statusText.text = "Accesso effettuato! Download dati..."
                loginPromptLayout.visibility = View.GONE
                swipeRefresh.visibility = View.VISIBLE
                if (dashboardWebView.url == null || !dashboardWebView.url!!.contains("dashboard.html")) {
                    dashboardWebView.loadUrl("file:///android_asset/dashboard.html")
                }
                syncGarminData()
            } else {
                progressBar.visibility = View.GONE
                statusText.text = "Scambio token non riuscito. Riprova il login."
            }
        }
    }

    private fun checkAuthStateAndInit() {
        if (GarminAuthManager.hasValidAuth(this)) {
            loginPromptLayout.visibility = View.GONE
            loginWebView.visibility = View.GONE
            swipeRefresh.visibility = View.VISIBLE
            dashboardWebView.loadUrl("file:///android_asset/dashboard.html")
        } else {
            swipeRefresh.visibility = View.GONE
            loginWebView.visibility = View.GONE
            loginPromptLayout.visibility = View.VISIBLE
        }
    }

    private fun startGarminWebLogin() {
        loginPromptLayout.visibility = View.GONE
        loginWebView.visibility = View.VISIBLE
        loginWebView.loadUrl(GARMIN_SSO_URL)
    }

    private fun syncGarminData() {
        swipeRefresh.isRefreshing = true
        lifecycleScope.launch {
            try {
                val jsonPayload = GarminDataFetcher.fetchWeightHistory(this@MainActivity)
                pushPayloadToDashboard(jsonPayload)
            } catch (e: Exception) {
                e.printStackTrace()
                Toast.makeText(this@MainActivity, e.message ?: "Errore di sincronizzazione", Toast.LENGTH_LONG).show()
                // Revert to cached if available
                pushCachedDataToDashboard()
            } finally {
                swipeRefresh.isRefreshing = false
                progressBar.visibility = View.GONE
            }
        }
    }

    private fun pushCachedDataToDashboard() {
        val cached = GarminAuthManager.getCachedData(this)
        if (!cached.isNullOrBlank()) {
            pushPayloadToDashboard(cached)
        } else if (GarminAuthManager.hasValidAuth(this)) {
            syncGarminData()
        }
    }

    private fun pushPayloadToDashboard(json: String) {
        val safeJson = json.replace("\\", "\\\\").replace("'", "\\'")
        dashboardWebView.post {
            dashboardWebView.evaluateJavascript("updateFromAndroid('$safeJson')", null)
        }
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (loginWebView.visibility == View.VISIBLE) {
                    if (loginWebView.canGoBack()) {
                        loginWebView.goBack()
                    } else {
                        loginWebView.visibility = View.GONE
                        loginPromptLayout.visibility = View.VISIBLE
                    }
                } else if (dashboardWebView.canGoBack()) {
                    dashboardWebView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    inner class WebAppInterface {
        @JavascriptInterface
        fun onDashboardReady() {
            runOnUiThread {
                pushCachedDataToDashboard()
            }
        }

        @JavascriptInterface
        fun syncData() {
            runOnUiThread {
                syncGarminData()
            }
        }

        @JavascriptInterface
        fun logout() {
            runOnUiThread {
                GarminAuthManager.clear(this@MainActivity)
                CookieManager.getInstance().removeAllCookies(null)
                checkAuthStateAndInit()
                Toast.makeText(this@MainActivity, "Account Garmin disconnesso", Toast.LENGTH_SHORT).show()
            }
        }
    }
}
