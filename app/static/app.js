// Save picks without reloading the page. Without JavaScript the forms still work.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button.team");
  if (!button || button.disabled) return;
  event.preventDefault();

  const form = button.form;
  const data = new FormData(form);
  data.set("pick", button.value);
  const buttons = form.querySelectorAll("button.team");
  buttons.forEach((b) => b.classList.add("pending"));

  try {
    const res = await fetch(form.action, {
      method: "POST",
      body: data,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body.ok) {
      alert(body.error || "The pick wasn't saved. Reload the page and try again.");
      return;
    }
    buttons.forEach((b) => {
      const picked = b === button;
      b.classList.toggle("picked", picked);
      b.setAttribute("aria-pressed", String(picked));
    });
    updateMissing();
  } catch {
    alert("The pick wasn't saved. Check your connection and try again.");
  } finally {
    buttons.forEach((b) => b.classList.remove("pending"));
  }
});

function updateMissing() {
  const line = document.getElementById("status-line");
  if (!line) return;
  const open = [...document.querySelectorAll(".game:not(.locked)")];
  const missing = open.filter((g) => !g.querySelector("button.team.picked")).length;
  line.textContent = missing
    ? ""
    : "All picks in. You can change them until each game kicks off.";
  if (missing) {
    line.append("You still have ");
    const strong = document.createElement("strong");
    strong.id = "missing-count";
    strong.textContent = missing;
    line.append(strong, missing === 1 ? " game to pick." : " games to pick.");
  }
}
