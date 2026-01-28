// Restore persisted theme preference before the page renders
(function () {
  const root = document.documentElement;
  const saved = localStorage.getItem("theme");
  if (saved === "dark") {
    root.classList.add("dark-mode");
  }
})();

// Toggle dark mode and persist the user's preference
function toggleDarkMode() {
  const root = document.documentElement;
  root.classList.toggle("dark-mode");

  localStorage.setItem(
    "theme",
    root.classList.contains("dark-mode") ? "dark" : "light"
  );
}


