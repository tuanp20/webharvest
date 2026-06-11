"""
StealthFetcher – anti-bot bypass via Playwright with stealth injection.

Implements techniques inspired by *playwright-stealth* and *camoufox*:
- Disable the ``webdriver`` flag (``navigator.webdriver`` → ``false``).
- Inject fake plugins, languages, platform values.
- Canvas fingerprint noise (random pixel perturbation).
- WebGL vendor/renderer spoofing.
- CDP (Chrome DevTools Protocol) detection evasion.
- Override ``navigator.permissions.query`` to hide automation signals.
- Spoof ``chrome.runtime`` and related objects.
- Add realistic ``window.chrome`` runtime stub.

All hardening is applied as JavaScript ``addInitScript`` snippets that
execute **before** any page script runs, so the page can never detect
the real values.

Dependencies: playwright (``pip install playwright && playwright install``)
"""

from __future__ import annotations

import logging
import random
import string
from typing import Any, Dict, List, Optional

from .dynamic import DynamicFetcher

logger = logging.getLogger("webharvest.fetchers.stealth")

# ─── Stealth JavaScript snippets ─────────────────────────────────────────────

# 1. Disable navigator.webdriver
_JS_DISABLE_WEBDRIVER = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => false,
    configurable: true
});
"""

# 2. Fake plugins array
_JS_FAKE_PLUGINS = """
(() => {
    const makePlugin = (name, filename, desc) => {
        const p = { name, filename, description: desc, length: 1 };
        p[0] = { type: 'application/pdf', suffixes: 'pdf', description: desc };
        return p;
    };
    const plugins = [
        makePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
        makePlugin('Chrome PDF Viewer', 'internal-pdf-viewer', ''),
        makePlugin('Chromium PDF Viewer', 'internal-pdf-viewer', ''),
    ];
    plugins.__proto__ = PluginArray.prototype;
    Object.defineProperty(navigator, 'plugins', {
        get: () => plugins,
        configurable: true,
    });
    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => {
            const mimes = [
                { type: 'application/pdf', suffixes: 'pdf', description: '', enabledPlugin: plugins[0] },
            ];
            mimes.__proto__ = MimeTypeArray.prototype;
            return mimes;
        },
        configurable: true,
    });
})();
"""

# 3. Fake languages
_JS_FAKE_LANGUAGES = """
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
});
Object.defineProperty(navigator, 'language', {
    get: () => 'en-US',
    configurable: true,
});
"""

# 4. Fake platform
_JS_FAKE_PLATFORM = """
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
    configurable: true,
});
"""

# 5. Spoof navigator.hardwareConcurrency
_JS_FAKE_HARDWARE = """
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => %d,
    configurable: true
});
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => %d,
    configurable: true
});
"""  # will be formatted at runtime

# 6. Canvas fingerprint noise
_JS_CANVAS_NOISE = """
(() => {
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type, quality) {
        if (type === 'image/png' || !type) {
            const ctx = this.getContext('2d');
            if (ctx) {
                const imageData = ctx.getImageData(0, 0, this.width, this.height);
                for (let i = 0; i < imageData.data.length; i += 4) {
                    // Perturb the R channel by ±1 on ~2% of pixels
                    if (Math.random() < 0.02) {
                        imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + (Math.random() > 0.5 ? 1 : -1)));
                    }
                }
                ctx.putImageData(imageData, 0, 0);
            }
        }
        return originalToDataURL.call(this, type, quality);
    };

    // Also perturb getImageData
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(sx, sy, sw, sh) {
        const imageData = origGetImageData.call(this, sx, sy, sw, sh);
        for (let i = 0; i < imageData.data.length; i += 4) {
            if (Math.random() < 0.01) {
                imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + (Math.random() > 0.5 ? 1 : -1)));
            }
        }
        return imageData;
    };
})();
"""

# 7. WebGL vendor/renderer spoofing
_JS_WEBGL_SPOOF = """
(() => {
    const getParam = WebGLRenderingContext.prototype.getParameter;
    const vendors = ['Google Inc. (NVIDIA)', 'Google Inc. (Intel)', 'Google Inc. (AMD)'];
    const renderers = [
        'ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0)',
        'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)',
        'ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)',
    ];
    const vendor = vendors[Math.floor(Math.random() * vendors.length)];
    const renderer = renderers[Math.floor(Math.random() * renderers.length)];

    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return vendor;   // UNMASKED_VENDOR_WEBGL
        if (parameter === 37446) return renderer;  // UNMASKED_RENDERER_WEBGL
        return getParam.call(this, parameter);
    };

    if (typeof WebGL2RenderingContext !== 'undefined') {
        const getParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return vendor;
            if (parameter === 37446) return renderer;
            return getParam2.call(this, parameter);
        };
    }
})();
"""

# 8. CDP detection evasion
_JS_CDP_EVASION = """
(() => {
    // Remove Runtime.enable and other CDP-leaking properties
    // Detect if window.cdc_ exists (Chromedriver artifacts)
    for (const key in window) {
        if (key.startsWith('cdc_') || key.startsWith('$cdc_') || key.startsWith('__webdriver')) {
            try { delete window[key]; } catch {}
        }
    }
    // Spoof chrome.runtime to avoid Cloudflare / Datadome checks
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: function() {},
            sendMessage: function() {},
            onMessage: { addListener: function() {} },
            PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
            PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
            OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        };
    }
})();
"""

# 9. Permissions query spoof (prevent detection via Notification / geolocation)
_JS_PERMISSIONS_SPOOF = """
(() => {
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) => (
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery.call(window.navigator.permissions, params)
    );
})();
"""

# 10. Override toString on patched functions to look native
_JS_PATCH_TOSTRING = """
(() => {
    const toStr = Function.prototype.toString;
    const nativeStr = 'function toString() { [native code] }';
    Function.prototype.toString = function() {
        if (this === Function.prototype.toString) return nativeStr;
        return toStr.call(this);
    };
})();
"""

# 11. Spooof screen dimensions with realistic values
_JS_SCREEN_SPOOF = """
(() => {
    const screens = [
        { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 },
        { width: 2560, height: 1440, availWidth: 2560, availHeight: 1400 },
        { width: 1536, height: 864,  availWidth: 1536, availHeight: 824 },
        { width: 1440, height: 900,  availWidth: 1440, availHeight: 860 },
    ];
    const s = screens[Math.floor(Math.random() * screens.length)];
    Object.defineProperties(screen, {
        width:        { get: () => s.width },
        height:       { get: () => s.height },
        availWidth:   { get: () => s.availWidth },
        availHeight:  { get: () => s.availHeight },
    });
    Object.defineProperty(window, 'outerWidth',  { get: () => s.width });
    Object.defineProperty(window, 'outerHeight', { get: () => s.height - 80 });
    Object.defineProperty(window, 'innerWidth',  { get: () => s.width - 16 });
    Object.defineProperty(window, 'innerHeight', { get: () => s.height - 160 });
})();
"""


# ─── StealthFetcher ──────────────────────────────────────────────────────────

class StealthFetcher(DynamicFetcher):
    """Playwright-based fetcher with comprehensive anti-bot stealth.

    Applies a suite of JavaScript ``addInitScript`` patches **before** any
    page script executes, defeating common bot-detection techniques:

    - ``navigator.webdriver`` set to ``false``.
    - Fake ``plugins``, ``mimeTypes``, ``languages``, ``platform``.
    - Canvas fingerprint noise (subtle pixel perturbation).
    - WebGL vendor / renderer spoofing.
    - CDP artifact cleanup (``$cdc_*``, ``__webdriver_*``).
    - ``chrome.runtime`` stub for Cloudflare / DataDome.
    - ``permissions.query`` override for Notification detection.
    - ``Function.prototype.toString`` tamper-evidence patch.
    - Realistic screen / window dimension spoofing.

    Inherits browser management, scrolling, JS execution from
    :class:`DynamicFetcher` and rate-limiting from :class:`BaseFetcher`.

    Parameters
    ----------
    user_agent : str | None
        Specific UA string. If *None*, one is randomly picked from
        the UA pool at browser-context creation time.
    **kwargs
        Forwarded to :class:`DynamicFetcher` / :class:`BaseFetcher`.
    """

    def __init__(self, *, user_agent: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._stealth_ua = user_agent

    # ------------------------------------------------------------------
    # Override: create a hardened browser context
    # ------------------------------------------------------------------
    def _ensure_browser(self) -> None:
        """Launch browser and inject stealth scripts via ``addInitScript``."""
        if self._browser is not None:
            return

        super()._ensure_browser()

        # Inject all stealth scripts
        context = self._browser_context
        scripts = self._build_stealth_scripts()
        for script in scripts:
            context.add_init_script(script)

        logger.info("StealthFetcher: %d stealth scripts injected", len(scripts))

    def _build_stealth_scripts(self) -> List[str]:
        """Return the list of JS stealth snippets to inject."""
        cores = random.choice([4, 8, 12, 16])
        memory = random.choice([4, 8, 16, 32])

        scripts = [
            _JS_DISABLE_WEBDRIVER,
            _JS_FAKE_PLUGINS,
            _JS_FAKE_LANGUAGES,
            _JS_FAKE_PLATFORM,
            _JS_FAKE_HARDWARE % (cores, memory),
            _JS_CANVAS_NOISE,
            _JS_WEBGL_SPOOF,
            _JS_CDP_EVASION,
            _JS_PERMISSIONS_SPOOF,
            _JS_PATCH_TOSTRING,
            _JS_SCREEN_SPOOF,
        ]

        # Inject a randomised extra noise script
        noise_seed = random.randint(0, 2**32)
        scripts.append(
            f"// Noise seed: {noise_seed}\n"
            f"Math.random = (function(orig) {{\n"
            f"  let seed = {noise_seed};\n"
            f"  return function() {{\n"
            f"    seed = (seed * 16807 + 0) % 2147483647;\n"
            f"    return (seed - 1) / 2147483646;\n"
            f"  }};\n"
            f"}})(Math.random);\n"
        )
        return scripts

    def get(
        self,
        url: str,
        *,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: Optional[int] = None,
        scroll_to_load: bool = False,
        max_scrolls: int = 20,
        scroll_delay: float = 1.5,
        execute_js: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        cookies: Optional[List[Dict[str, Any]]] = None,
    ) -> "FetchResponse":
        """Stealth-fetch a URL.

        Identical interface to :meth:`DynamicFetcher.get` but with all
        anti-bot patches active.
        """
        logger.info("StealthFetcher GET %s", url)
        return super().get(
            url,
            wait_for_selector=wait_for_selector,
            wait_for_timeout=wait_for_timeout,
            scroll_to_load=scroll_to_load,
            max_scrolls=max_scrolls,
            scroll_delay=scroll_delay,
            execute_js=execute_js,
            headers=headers,
            timeout=timeout,
            cookies=cookies,
        )

    # ------------------------------------------------------------------
    # Advanced stealth helpers
    # ------------------------------------------------------------------
    def humanize_mouse(self, page: Any) -> None:
        """Inject subtle mouse-movement noise to mimic human interaction."""
        for _ in range(random.randint(3, 8)):
            x = random.randint(100, 1800)
            y = random.randint(100, 900)
            page.mouse.move(x, y, steps=random.randint(5, 20))

    def random_scroll(self, page: Any, *, scrolls: int = 5) -> None:
        """Perform randomised scroll actions (direction + distance vary)."""
        for _ in range(scrolls):
            delta = random.randint(200, 800)
            if random.random() < 0.1:
                delta = -delta  # occasional upward scroll
            page.mouse.wheel(0, delta)
            import time
            time.sleep(random.uniform(0.5, 2.0))

    def type_human_like(self, page: Any, selector: str, text: str) -> None:
        """Type text into an element with random inter-key delays."""
        page.click(selector)
        for char in text:
            page.keyboard.type(char)
            import time
            time.sleep(random.uniform(0.05, 0.2))

    def __repr__(self) -> str:
        return (
            f"StealthFetcher(browser={self._browser_type_name!r}, "
            f"headless={self._headless}, impersonate={self._impersonate})"
        )
