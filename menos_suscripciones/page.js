(function () {
  var DATA = JSON.parse(document.getElementById("data").textContent);
  var TOOLS = DATA.tools, T = DATA.t;
  var tbody = document.getElementById("dir"), countEl = document.getElementById("count"),
      emptyEl = document.getElementById("empty"), q = document.getElementById("q"),
      chips = Array.prototype.slice.call(document.querySelectorAll(".chip")), filter = "all";
  try { filter = localStorage.getItem("ms-filter") || "all"; } catch (err) {}
  if (!chips.some(function (c) { return c.dataset.f === filter; })) filter = "all";

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function matches(t) {
    switch (filter) {
      case "try": return t.status === "try";
      case "pay": return t.saving > 0;
      case "local": return t.runs !== "server";
      case "server": return t.runs === "server";
      case "have": return t.status === "have";
      default: return true;
    }
  }
  function render() {
    var term = q.value.trim().toLowerCase();
    var rows = TOOLS.filter(function (t) {
      if (!matches(t)) return false;
      return !term || [t.name, t.replaces.join(" "), t.category, t.what, t.runs_label, t.status_label, t.note].join(" ").toLowerCase().indexOf(term) !== -1;
    });
    tbody.innerHTML = rows.map(function (t) {
      var note = (t.saving ? '<span class="saving">' + esc(T.saves.replace("{n}", t.saving)) + '</span> ' : '') + esc(t.note);
      return '<tr><td><a class="tool" href="' + esc(t.url) + '" target="_blank" rel="noopener">' + esc(t.name) + '</a><div class="small">' + esc(t.category) + '</div></td>' +
        '<td>' + esc(t.replaces.join(", ")) + '</td><td>' + esc(t.what) + '</td>' +
        '<td><span class="pill where">' + esc(t.runs_label) + '</span></td>' +
        '<td><span class="pill ' + t.status_class + '">' + esc(t.status_label) + '</span></td>' +
        '<td>' + (note.trim() ? note : '<span class="small">—</span>') + '</td></tr>';
    }).join("");
    emptyEl.hidden = rows.length > 0;
    countEl.textContent = T.count.replace("{n}", rows.length).replace("{total}", TOOLS.length);
    chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.f === filter)); });
  }
  chips.forEach(function (c) {
    c.addEventListener("click", function () {
      filter = c.dataset.f;
      try { localStorage.setItem("ms-filter", filter); } catch (err) {}
      render();
    });
  });
  q.addEventListener("input", render);
  render();
})();
