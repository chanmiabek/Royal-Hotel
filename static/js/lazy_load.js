(function () {
    "use strict";

    function loadFragment(section) {
        var url = section.getAttribute("data-lazy-fragment");
        if (!url || section.dataset.lazyLoaded === "true") {
            return;
        }

        section.dataset.lazyLoaded = "true";
        section.setAttribute("aria-busy", "true");

        var status = section.querySelector("[data-lazy-status]");
        if (status) {
            status.textContent = section.dataset.loadingText || "Loading...";
        }

        window.fetch(url, {
            credentials: "same-origin",
            headers: { "X-Requested-With": "fetch" }
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Lazy fragment request failed.");
                }
                return response.text();
            })
            .then(function (html) {
                section.outerHTML = html;
            })
            .catch(function () {
                section.dataset.lazyLoaded = "false";
                section.setAttribute("aria-busy", "false");
                if (status) {
                    status.textContent = section.dataset.errorText || "Content could not be loaded.";
                }
            });
    }

    function initialiseLazyFragments(root) {
        var sections = [];
        if (root.matches && root.matches("[data-lazy-fragment]")) {
            sections.push(root);
        }
        sections = sections.concat(Array.prototype.slice.call(root.querySelectorAll("[data-lazy-fragment]")));

        sections.forEach(function (section) {
            if (section.dataset.lazyInitialised === "true") {
                return;
            }
            section.dataset.lazyInitialised = "true";

            if (!("IntersectionObserver" in window)) {
                loadFragment(section);
                return;
            }

            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) {
                        return;
                    }
                    observer.unobserve(entry.target);
                    loadFragment(entry.target);
                });
            }, { rootMargin: "300px 0px" });

            observer.observe(section);
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initialiseLazyFragments(document);
    });

    document.addEventListener("rh:partial-load", function (event) {
        initialiseLazyFragments(event.detail.root);
    });
})();
