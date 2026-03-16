(() => {
  const buttons = document.querySelectorAll("[data-toggle-password]");

  const setButtonState = (button, isVisible) => {
    const showLabel = button.getAttribute("data-label-show") || "Show password";
    const hideLabel = button.getAttribute("data-label-hide") || "Hide password";

    const label = isVisible ? hideLabel : showLabel;
    button.setAttribute("aria-pressed", isVisible ? "true" : "false");
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);

    const icon = button.querySelector("i");
    if (icon) {
      icon.classList.toggle("fa-eye", !isVisible);
      icon.classList.toggle("fa-eye-slash", isVisible);
    }
  };

  buttons.forEach((button) => {
    const targetId = button.getAttribute("data-toggle-password");
    if (!targetId) return;

    const input = document.getElementById(targetId);
    if (!input) return;

    setButtonState(button, input.type === "text");

    button.addEventListener("click", () => {
      const isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      setButtonState(button, !isVisible);
    });
  });
})();

