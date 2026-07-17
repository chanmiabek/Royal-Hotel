(function () {
    "use strict";

    var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var pointerSelector = [
        ".hotel-card",
        ".result-card",
        ".hotel-result-card",
        ".rh-home-trust__card",
        ".rh-home-offer",
        ".search-panel",
        ".btn",
        "button",
        ".mobile-more__item",
        ".footer-float-btn"
    ].join(",");
    var revealSelector = [
        "#rh-page-content > section",
        "#rh-page-content section > .container",
        ".hotel-card",
        ".result-card",
        ".hotel-result-card",
        ".room-row",
        ".member-panel",
        ".member-hero",
        ".loyalty-banner",
        ".admin-card",
        ".dashboard-card",
        ".review-card",
        ".hotel-filter-block",
        ".form-group",
        ".rh-home-trust__card",
        ".rh-home-offer",
        ".rh-featured-group",
        ".hotel-results-header",
        ".section-header"
    ].join(",");

    function enhancePointerTarget(element) {
        if (!element || element.dataset.rhInteractionReady === "true") {
            return;
        }
        element.dataset.rhInteractionReady = "true";
        element.classList.add("rh-pointer-aware", "rh-hover-lift");

        element.addEventListener("pointermove", function (event) {
            var rect = element.getBoundingClientRect();
            var x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
            var y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
            element.style.setProperty("--rh-pointer-x", x.toFixed(2) + "%");
            element.style.setProperty("--rh-pointer-y", y.toFixed(2) + "%");
        });

        element.addEventListener("mouseover", function () {
            element.classList.add("is-mouseover");
        });

        element.addEventListener("mouseout", function () {
            element.classList.remove("is-mouseover");
            element.classList.remove("rh-pressed");
        });

        element.addEventListener("pointerdown", function () {
            element.classList.add("rh-pressed");
        });

        element.addEventListener("pointerup", function () {
            element.classList.remove("rh-pressed");
        });
    }

    function enhanceRevealTarget(element, observer) {
        if (!element || element.dataset.rhRevealReady === "true") {
            return;
        }
        element.dataset.rhRevealReady = "true";
        element.classList.add("rh-animate-in");
        if (reducedMotion || !observer) {
            element.classList.add("is-visible");
            return;
        }
        observer.observe(element);
    }

    function hydrateInteractions(root) {
        var scope = root || document;
        var observer = null;

        if (!reducedMotion && "IntersectionObserver" in window) {
            observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("is-visible");
                        observer.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
        }

        scope.querySelectorAll(pointerSelector).forEach(enhancePointerTarget);
        scope.querySelectorAll(revealSelector).forEach(function (element, index) {
            element.style.setProperty("--rh-reveal-delay", Math.min(index % 8, 7) * 45 + "ms");
            enhanceRevealTarget(element, observer);
        });
    }

    function dismissToast(toast) {
        if (!toast || toast.dataset.rhToastClosing === "true") {
            return;
        }
        toast.dataset.rhToastClosing = "true";
        toast.classList.add("is-dismissing");
        window.setTimeout(function () {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, reducedMotion ? 0 : 220);
    }

    function hydrateToasts(root) {
        var scope = root || document;
        scope.querySelectorAll(".rh-toast").forEach(function (toast) {
            if (toast.dataset.rhToastReady === "true") {
                return;
            }
            toast.dataset.rhToastReady = "true";
            var dismissAfter = parseInt(toast.getAttribute("data-auto-dismiss"), 10);
            var closeButton = toast.querySelector("[data-dismiss='alert'], .rh-toast__close");

            if (closeButton) {
                closeButton.addEventListener("click", function (event) {
                    event.preventDefault();
                    dismissToast(toast);
                });
            }

            if (dismissAfter > 0) {
                window.setTimeout(function () {
                    dismissToast(toast);
                }, dismissAfter);
            }
        });
    }

    function startButtonLoading(button) {
        if (!button || button.classList.contains("rh-button-loading")) {
            return;
        }
        var isInput = button.tagName === "INPUT";
        button.dataset.rhLoadingInput = isInput ? "true" : "false";
        button.dataset.rhLoadingOriginal = isInput ? button.value : button.innerHTML;
        button.dataset.rhLoadingMinWidth = button.style.minWidth || "";
        button.style.minWidth = Math.ceil(button.getBoundingClientRect().width) + "px";
        button.classList.add("rh-button-loading");
        button.setAttribute("aria-busy", "true");
        button.disabled = true;
        var buttonText = (isInput ? button.value : button.textContent).trim().toLowerCase();
        var inferredLabel = buttonText.indexOf("delete") >= 0 ? "Deleting..." :
            buttonText.indexOf("sign in") >= 0 || buttonText.indexOf("login") >= 0 ? "Signing in..." :
            buttonText.indexOf("register") >= 0 || buttonText.indexOf("create account") >= 0 ? "Creating account..." :
            buttonText.indexOf("save") >= 0 || buttonText.indexOf("update") >= 0 ? "Saving..." :
            buttonText.indexOf("upload") >= 0 ? "Uploading..." : "Submitting...";
        var label = button.getAttribute("data-loading-text") || inferredLabel;
        if (isInput) {
            button.value = label;
        } else {
            button.innerHTML = '<span class="rh-button-loading__content"><span class="rh-button-spinner" aria-hidden="true"></span><span>' + label + '</span></span>';
        }
    }

    function stopButtonLoading(button) {
        if (!button || !button.classList.contains("rh-button-loading")) {
            return;
        }
        if (button.dataset.rhLoadingOriginal !== undefined) {
            if (button.dataset.rhLoadingInput === "true") {
                button.value = button.dataset.rhLoadingOriginal;
            } else {
                button.innerHTML = button.dataset.rhLoadingOriginal;
            }
            delete button.dataset.rhLoadingOriginal;
            delete button.dataset.rhLoadingInput;
        }
        button.classList.remove("rh-button-loading");
        button.style.minWidth = button.dataset.rhLoadingMinWidth || "";
        delete button.dataset.rhLoadingMinWidth;
        button.removeAttribute("aria-busy");
        button.disabled = false;
    }

    function resetLoadingButtons(root) {
        (root || document).querySelectorAll(".rh-button-loading").forEach(stopButtonLoading);
    }

    function hydrateDropdowns(root) {
        (root || document).querySelectorAll(".top-menu .dropdown").forEach(function (dropdown) {
            if (dropdown.dataset.rhDropdownReady === "true") return;
            dropdown.dataset.rhDropdownReady = "true";
            var toggle = dropdown.querySelector(":scope > .dropdown-toggle");
            var menu = dropdown.querySelector(":scope > .dropdown-menu");
            if (!toggle || !menu) return;
            function setOpen(open) {
                dropdown.classList.toggle("rh-hover-open", open);
                toggle.setAttribute("aria-expanded", open ? "true" : "false");
            }
            dropdown.addEventListener("mouseenter", function () {
                if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) setOpen(true);
            });
            dropdown.addEventListener("mouseleave", function () {
                if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) setOpen(false);
            });
            dropdown.addEventListener("focusin", function () { setOpen(true); });
            dropdown.addEventListener("focusout", function (event) {
                if (!dropdown.contains(event.relatedTarget)) setOpen(false);
            });
            toggle.addEventListener("keydown", function (event) {
                if (event.key !== "ArrowDown") return;
                event.preventDefault();
                setOpen(true);
                var first = menu.querySelector("a, button, [tabindex]:not([tabindex='-1'])");
                if (first) first.focus();
            });
        });
    }

    function hydrateAdminSidebar(root) {
        var shell = (root || document).querySelector(".admin-shell");
        if (!shell || shell.dataset.rhAdminReady === "true") return;
        shell.dataset.rhAdminReady = "true";
        var toggle = shell.querySelector("[data-admin-sidebar-toggle]");
        function setOpen(open) {
            shell.classList.toggle("admin-nav-open", open);
            document.body.classList.toggle("admin-nav-lock", open);
            if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
        }
        if (toggle) toggle.addEventListener("click", function () { setOpen(true); });
        shell.querySelectorAll("[data-admin-sidebar-close]").forEach(function (item) {
            item.addEventListener("click", function () { setOpen(false); });
        });
        shell.querySelectorAll(".admin-sidebar a").forEach(function (item) {
            item.addEventListener("click", function () { setOpen(false); });
        });
    }

    document.addEventListener("click", function (event) {
        document.querySelectorAll(".top-menu .dropdown.rh-hover-open").forEach(function (dropdown) {
            if (!dropdown.contains(event.target)) dropdown.classList.remove("rh-hover-open");
        });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        document.querySelectorAll(".top-menu .dropdown.rh-hover-open").forEach(function (dropdown) {
            dropdown.classList.remove("rh-hover-open");
            var toggle = dropdown.querySelector(".dropdown-toggle");
            if (toggle) { toggle.setAttribute("aria-expanded", "false"); toggle.focus(); }
        });
        var shell = document.querySelector(".admin-shell.admin-nav-open");
        if (shell) {
            shell.classList.remove("admin-nav-open");
            document.body.classList.remove("admin-nav-lock");
            var adminToggle = shell.querySelector("[data-admin-sidebar-toggle]");
            if (adminToggle) { adminToggle.setAttribute("aria-expanded", "false"); adminToggle.focus(); }
        }
    });

    window.RoyalLoadingButton = { start: startButtonLoading, stop: stopButtonLoading };

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!form || form.tagName !== "FORM" || form.hasAttribute("data-no-loading")) {
            return;
        }
        // Target-level AJAX handlers run before this delegated handler. They call
        // preventDefault(), so only forms that will navigate receive this state.
        if (event.defaultPrevented) {
            return;
        }
        var button = event.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
        startButtonLoading(button);
    });

    document.addEventListener("rh:button-loading-stop", function (event) {
        if (event.detail && event.detail.button) {
            stopButtonLoading(event.detail.button);
        } else {
            resetLoadingButtons(document);
        }
    });

    window.addEventListener("pageshow", function () {
        resetLoadingButtons(document);
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            hydrateInteractions(document);
            hydrateToasts(document);
            hydrateDropdowns(document);
            hydrateAdminSidebar(document);
        });
    } else {
        hydrateInteractions(document);
        hydrateToasts(document);
        hydrateDropdowns(document);
        hydrateAdminSidebar(document);
    }

    document.addEventListener("htmx:afterSwap", function (event) {
        hydrateInteractions(event.target || document);
        hydrateToasts(event.target || document);
        hydrateDropdowns(event.target || document);
        hydrateAdminSidebar(event.target || document);
    });

    document.addEventListener("rh:partial-load", function (event) {
        hydrateInteractions((event.detail && event.detail.root) || document);
        hydrateToasts((event.detail && event.detail.root) || document);
    });
})();
