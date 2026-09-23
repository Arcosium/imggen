package uk.aive.imggen

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.ContentValues
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.view.View
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import uk.aive.imggen.databinding.ActivityMainBinding

/**
 * imggen.ai-ve.uk(Image Studio)를 감싸는 WebView 셸. ArkInsight 셸에서 가져왔다.
 *
 * 화면·기능은 전부 웹(app.py)에서 오므로 웹을 고치면 앱은 다시 빌드하지 않아도 된다.
 * 앱이 더하는 것: 사진 올리기(파일 선택기) · 결과 저장(다운로드) · 화면 꺼짐 방지(한 장 8분) ·
 * 상단 진행바 · 오프라인 화면 · 뒤로가기 2번 종료 · 외부링크 분리.
 * 당겨서 새로고침은 끈다. 생성 중에 새로고침되면 진행 화면을 잃는다.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var isPageLoaded = false

    private var lastBackPressTime: Long = 0L
    private var backPressToast: Toast? = null

    // <input type=file> 콜백. WebView 는 onShowFileChooser 를 구현하지 않으면 업로드 칸이 무반응이다.
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private val pickFile = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data))
        fileCallback = null
    }

    companion object {
        private const val WEB_URL = "https://imggen.ai-ve.uk"
        private const val HOST = "imggen.ai-ve.uk"
        private const val KEY_URL = "current_url"
        private const val BACK_EXIT_WINDOW_MS = 2000L
        private const val BG = "#F5F1E8"        // app.py CSS 의 --paper
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        val splashScreen = installSplashScreen()
        splashScreen.setKeepOnScreenCondition { !isPageLoaded }

        super.onCreate(savedInstanceState)
        setupEdgeToEdge()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)   // 생성 한 장 약 8분 — 화면이 꺼지면 진행 연결이 끊긴다

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        applySystemBarInsets()

        setupWebView()
        setupPullToRefresh()
        setupBackNavigation()
        binding.btnRetry.setOnClickListener {
            if (isNetworkAvailable()) { hideErrorState(); loadUrl(WEB_URL) }
        }

        val urlToLoad = savedInstanceState?.getString(KEY_URL) ?: WEB_URL
        if (isNetworkAvailable()) loadUrl(urlToLoad) else showErrorState()
    }

    private fun setupEdgeToEdge() {
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.parseColor(BG)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = true       // 종이 배경 — 아이콘은 검정
            isAppearanceLightNavigationBars = true
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS)
    }

    /**
     * edge-to-edge 를 켰으면 누군가는 인셋을 소비해야 한다 — 아무도 안 하면 WebView 가 상태바
     * 아래로 파고들어 대시보드 헤더가 시계·배터리와 겹친다. 루트에 패딩으로 물려 WebView·
     * 프로그레스바·에러화면이 한꺼번에 시스템 바(+노치)를 피하게 한다.
     */
    private fun applySystemBarInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { v, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        ViewCompat.requestApplyInsets(binding.root)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        binding.webView.apply {
            setBackgroundColor(Color.parseColor(BG))
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                useWideViewPort = true
                loadWithOverviewMode = true
                setSupportZoom(false)
                builtInZoomControls = false
                displayZoomControls = false
                cacheMode = WebSettings.LOAD_DEFAULT
                userAgentString = "$userAgentString ImageStudioApp/1.0"
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            }
            CookieManager.getInstance().let {
                it.setAcceptCookie(true)
                it.setAcceptThirdPartyCookies(this, true)
            }
            webViewClient = AppWebViewClient()
            webChromeClient = AppChromeClient()
            addJavascriptInterface(FileBridge(), "ArkBridge")
            setDownloadListener { url, _, disposition, mime, _ -> download(url, disposition, mime) }
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
        }
    }

    /**
     * 편집 탭 '다운로드'·설명서 원본은 같은 도메인 파일 주소를 <a download> 로 연다 → 여기로 온다.
     * 파일 주소는 로그인 쿠키가 있어야 받아지므로 DownloadManager 에 쿠키를 실어 보낸다.
     */
    private fun download(url: String, disposition: String?, mime: String?) {
        val name = URLUtil.guessFileName(url, disposition, mime)
        try {
            val req = DownloadManager.Request(Uri.parse(url))
                .addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url) ?: "")
                .addRequestHeader("User-Agent", binding.webView.settings.userAgentString)
                .setMimeType(mime)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
            getSystemService(DownloadManager::class.java).enqueue(req)
            Toast.makeText(this, "다운로드 폴더에 저장 중: $name", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "저장 실패: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    /**
     * 생성 탭 갤러리의 내려받기는 fetch → blob URL → <a download>.click() → 곧바로 revoke 한다.
     * WebView 는 blob 앵커에 DownloadListener 를 부르지 않고, revoke 뒤엔 다시 읽을 수도 없다.
     * 그래서 createObjectURL 때 blob 을 붙잡아 두고, 앵커 클릭을 가로채 FileBridge 로 넘긴다.
     */
    private val blobHook = """
        (function(){ if (window.__blobHook) return; window.__blobHook = 1;
          const keep = new Map(), mk = URL.createObjectURL.bind(URL);
          URL.createObjectURL = function(b){ const u = mk(b); if (b instanceof Blob) keep.set(u, b); return u; };
          const click = HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click = function(){
            const b = keep.get(this.href);
            if (!b || !this.hasAttribute('download')) return click.call(this);
            const name = this.download || 'image.png', f = new FileReader();
            f.onload = () => ArkBridge.saveBase64(name, b.type, f.result.split(',')[1]);
            f.readAsDataURL(b);
          };
        })();
    """.trimIndent()

    /** 웹 → 네이티브 파일 저장 브리지(blob 다운로드용). MediaStore 로 공용 Downloads 에 저장(minSdk 29). */
    inner class FileBridge {
        @JavascriptInterface
        fun saveBase64(filename: String, mime: String, b64: String) {
            try {
                val bytes = Base64.decode(b64, Base64.DEFAULT)
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, filename)
                    put(MediaStore.Downloads.MIME_TYPE, mime.ifBlank { "application/octet-stream" })
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
                val resolver = contentResolver
                val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw IllegalStateException("MediaStore insert 실패")
                resolver.openOutputStream(uri)?.use { it.write(bytes) }
                    ?: throw IllegalStateException("출력 스트림 열기 실패")
                values.clear()
                values.put(MediaStore.Downloads.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
                runOnUiThread {
                    Toast.makeText(this@MainActivity, "다운로드 폴더에 저장됨: $filename", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this@MainActivity, "저장 실패: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun setupPullToRefresh() {
        binding.swipeRefresh.isEnabled = false
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (binding.webView.canGoBack()) { binding.webView.goBack(); return }
                val now = System.currentTimeMillis()
                if (now - lastBackPressTime <= BACK_EXIT_WINDOW_MS) {
                    backPressToast?.cancel(); finish(); return
                }
                lastBackPressTime = now
                backPressToast?.cancel()
                backPressToast = Toast.makeText(
                    this@MainActivity, "한 번 더 누르면 종료됩니다", Toast.LENGTH_SHORT
                ).also { it.show() }
            }
        })
    }

    private fun loadUrl(url: String) {
        binding.errorContainer.visibility = View.GONE
        binding.webView.visibility = View.VISIBLE
        binding.webView.loadUrl(url)
    }

    private fun showErrorState() {
        binding.webView.visibility = View.GONE
        binding.errorContainer.visibility = View.VISIBLE
        binding.progressBar.visibility = View.GONE
        binding.swipeRefresh.isRefreshing = false
    }

    private fun hideErrorState() {
        binding.errorContainer.visibility = View.GONE
        binding.webView.visibility = View.VISIBLE
    }

    private fun isNetworkAvailable(): Boolean {
        val cm = getSystemService(ConnectivityManager::class.java)
        val network = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(network) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(KEY_URL, binding.webView.url)
        binding.webView.saveState(outState)
    }

    override fun onRestoreInstanceState(savedInstanceState: Bundle) {
        super.onRestoreInstanceState(savedInstanceState)
        binding.webView.restoreState(savedInstanceState)
    }

    inner class AppWebViewClient : WebViewClient() {
        override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
            super.onPageStarted(view, url, favicon)
            binding.progressBar.visibility = View.VISIBLE
        }

        override fun onPageFinished(view: WebView?, url: String?) {
            super.onPageFinished(view, url)
            isPageLoaded = true
            view?.evaluateJavascript(blobHook, null)
            binding.progressBar.visibility = View.GONE
            binding.swipeRefresh.isRefreshing = false
            CookieManager.getInstance().flush()
        }

        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
            val url = request?.url?.toString() ?: return false
            if (url.contains(HOST)) return false
            try {                                   // 외부 링크는 시스템 브라우저로
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            } catch (_: Exception) { /* 핸들러 없는 URL 무시 */ }
            return true
        }

        override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
            super.onReceivedError(view, request, error)
            if (request?.isForMainFrame == true) showErrorState()
        }
    }

    inner class AppChromeClient : WebChromeClient() {
        override fun onShowFileChooser(view: WebView?, callback: ValueCallback<Array<Uri>>?,
                                       params: FileChooserParams?): Boolean {
            fileCallback?.onReceiveValue(null)
            fileCallback = callback
            return try {
                pickFile.launch(params!!.createIntent()); true
            } catch (_: Exception) {
                fileCallback = null; false
            }
        }

        override fun onProgressChanged(view: WebView?, newProgress: Int) {
            super.onProgressChanged(view, newProgress)
            binding.progressBar.progress = newProgress
            if (newProgress >= 100) binding.progressBar.visibility = View.GONE
        }
    }
}
