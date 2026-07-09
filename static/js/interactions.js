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
        ".hotel-card",
        ".result-card",
        ".hotel-result-card",
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
        scope.querySelectorAll(revealSelector).forEach(function (element) {
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

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            hydrateInteractions(document);
            hydrateToasts(document);
        });
    } else {
        hydrateInteractions(document);
        hydrateToasts(document);
    }

    document.addEventListener("htmx:afterSwap", function (event) {
        hydrateInteractions(event.target || document);
        hydrateToasts(event.target || document);
    });

    document.addEventListener("rh:partial-load", function (event) {
        hydrateInteractions((event.detail && event.detail.root) || document);
        hydrateToasts((event.detail && event.detail.root) || document);
    });
})();
