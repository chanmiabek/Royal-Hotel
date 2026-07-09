(function () {
    "use strict";

    var rootSelector = "#rh-page-content";
    var activeClass = "rh-section-loading";
    var controller = null;
    var lastUrl = window.location.href;

    function getRoot() {
        return document.querySelector(rootSelector);
    }

    function isPlainLeftClick(event) {
        return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
    }

    function shouldSkipLink(link, event) {
        if (!link || event.defaultPrevented || !isPlainLeftClick(event)) {
            return true;
        }

        if (link.matches("[data-no-partial], [data-no-skeleton], .no-partial, .no-skeleton, [download]")) {
            return true;
        }

        var target = (link.getAttribute("target") || "").trim();
        var href = (link.getAttribute("href") || "").trim();
        if (target || !href || href.charAt(0) === "#") {
            return true;
        }

        if (/^(mailto:|tel:|javascript:)/i.test(href)) {
            return true;
        }

        var url;
        try {
            url = new URL(href, window.location.href);
        } catch (error) {
            return true;
        }

        if (url.origin !== window.location.origin) {
            return true;
        }

        if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) {
            return true;
        }

        return false;
    }

    function startLoading(root) {
        if (!root) {
            return;
        }
        root.classList.add(activeClass);
        root.setAttribute("aria-busy", "true");
    }

    function stopLoading(root) {
        if (!root) {
            return;
        }
        root.classList.remove(activeClass);
        root.removeAttribute("aria-busy");
    }

    function updateActiveLinks(url) {
        var path = url.pathname.replace(/\/+$/, "") || "/";
        document.querySelectorAll("#header a[href], #mobile-menu-panel a[href]").forEach(function (link) {
            var item = link.closest("li");
            if (!item) {
                return;
            }

            var linkUrl;
            try {
                linkUrl = new URL(link.getAttribute("href"), window.location.href);
            } catch (error) {
                return;
            }

            var linkPath = linkUrl.pathname.replace(/\/+$/, "") || "/";
            item.classList.toggle("active", linkUrl.origin === url.origin && linkPath === path);
        });
    }

    function executeScripts(container) {
        container.querySelectorAll("script").forEach(function (oldScript) {
            var newScript = document.createElement("script");
            Array.prototype.slice.call(oldScript.attributes).forEach(function (attr) {
                newScript.setAttribute(attr.name, attr.value);
            });
            newScript.text = oldScript.text || oldScript.textContent || "";
            oldScript.parentNode.replaceChild(newScript, oldScript);
        });
    }

    function syncHeadAssets(doc) {
        doc.querySelectorAll("link[rel='stylesheet'][href]").forEach(function (incomingLink) {
            var href = incomingLink.href || incomingLink.getAttribute("href");
            var exists = Array.prototype.some.call(document.head.querySelectorAll("link[rel='stylesheet'][href]"), function (link) {
                return link.href === href || link.getAttribute("href") === href;
            });
            if (!href || exists) {
                return;
            }
            document.head.appendChild(incomingLink.cloneNode(true));
        });

        doc.querySelectorAll("head style").forEach(function (incomingStyle, index) {
            var key = "rh-style-" + btoa(unescape(encodeURIComponent(incomingStyle.textContent || ""))).slice(0, 32) + "-" + index;
            if (document.head.querySelector("style[data-rh-partial-style='" + key + "']")) {
                return;
            }
            var style = incomingStyle.cloneNode(true);
            style.setAttribute("data-rh-partial-style", key);
            document.head.appendChild(style);
        });
    }

    function swapContent(html, url, pushState) {
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, "text/html");
        var incoming = doc.querySelector(rootSelector);
        var current = getRoot();

        if (!incoming || !current) {
            window.location.href = url.href;
            return;
        }

        syncHeadAssets(doc);
        current.replaceWith(incoming);
        executeScripts(incoming);

        document.title = doc.title || document.title;
        if (pushState) {
            window.history.pushState({ partial: true }, document.title, url.href);
        }

        updateActiveLinks(url);
        window.scrollTo({ top: 0, behavior: "smooth" });
        incoming.focus({ preventScroll: true });

        document.dispatchEvent(new CustomEvent("rh:partial-load", {
            detail: { root: incoming, url: url.href }
        }));
    }

    function loadSection(url, pushState) {
        var root = getRoot();
        if (!root) {
            window.location.href = url.href;
            return;
        }

        if (controller) {
            controller.abort();
        }
        controller = new AbortController();
        startLoading(root);

        window.fetch(url.href, {
            method: "GET",
            credentials: "same-origin",
            headers: {
                "X-Requested-With": "fetch",
                "Accept": "text/html"
            },
            signal: controller.signal
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Page request failed.");
                }
                return response.text();
            })
            .then(function (html) {
                lastUrl = url.href;
                swapContent(html, url, pushState);
            })
            .catch(function (error) {
                if (error.name === "AbortError") {
                    return;
                }
                window.location.href = url.href;
            })
            .finally(function () {
                stopLoading(getRoot());
                controller = null;
            });
    }

    document.addEventListener("click", function (event) {
        var link = event.target.closest("a[href]");
        if (shouldSkipLink(link, event)) {
            return;
        }

        var url = new URL(link.getAttribute("href"), window.location.href);
        if (url.href === lastUrl) {
            return;
        }

        event.preventDefault();
        loadSection(url, true);
    }, true);

    window.addEventListener("popstate", function () {
        loadSection(new URL(window.location.href), false);
    });
})();
