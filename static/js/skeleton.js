(function () {
    "use strict";

    var loader = document.querySelector("[data-page-skeleton]");
    var loadingClass = "rh-loading";
    var showTimer = null;

    function showLoader() {
        window.clearTimeout(showTimer);
        showTimer = window.setTimeout(function () {
            document.documentElement.classList.add(loadingClass);
            if (loader) {
                loader.classList.add("is-active");
                loader.setAttribute("aria-hidden", "false");
            }
        }, 160);
    }

    function hideLoader() {
        window.clearTimeout(showTimer);
        document.documentElement.classList.remove(loadingClass);
        if (loader) {
            loader.classList.remove("is-active");
            loader.setAttribute("aria-hidden", "true");
        }
    }

    function isPartialNavigationLink(link, href) {
        if (!document.querySelector("[data-partial-root]")) {
            return false;
        }
        if (link.matches("[data-no-partial], .no-partial, [download]")) {
            return false;
        }
        try {
            var url = new URL(href, window.location.href);
            return url.origin === window.location.origin && href.charAt(0) !== "#";
        } catch (error) {
            return false;
        }
    }

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!form || form.matches("[data-no-skeleton], [target], .no-skeleton")) {
            return;
        }
        showLoader();
    }, true);

    document.addEventListener("click", function (event) {
        var link = event.target.closest("a[href]");
        if (!link || link.matches("[data-no-skeleton], .no-skeleton")) {
            return;
        }

        var href = link.getAttribute("href") || "";
        var target = link.getAttribute("target");
        var isHashOnly = href.charAt(0) === "#";
        var isScriptLink = href.indexOf("javascript:") === 0 || href.indexOf("tel:") === 0 || href.indexOf("mailto:") === 0;
        if (target || isHashOnly || isScriptLink || isPartialNavigationLink(link, href) || event.defaultPrevented || event.button !== 0) {
            return;
        }

        showLoader();
    }, true);

    document.addEventListener("htmx:beforeRequest", showLoader);
    document.addEventListener("htmx:afterOnLoad", hideLoader);
    document.addEventListener("htmx:responseError", hideLoader);
    document.addEventListener("htmx:sendError", hideLoader);
    window.addEventListener("pageshow", hideLoader);
})();
