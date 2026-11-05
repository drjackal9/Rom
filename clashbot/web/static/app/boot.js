(function () {
  const root = document.getElementById("app");
  if (!root) { return; }
  const slug = root.dataset.slug;
  const live = root.dataset.live;
  if (!slug || !live) { return; }
  const tg = window.Telegram && window.Telegram.WebApp;
  const signed = (tg && tg.initData) || "";
  const boot = { state: null, source: null, events: [] };
  boot.state = fetch("/app/" + slug + "/state", { headers: { "X-Init-Data": signed } })
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null);
  boot.source = new EventSource(live + "?init=" + encodeURIComponent(signed));
  boot.source.addEventListener("state", (event) => {
    if (window.clanboardBoot === boot) { boot.events.push(JSON.parse(event.data)); }
  });
  window.clanboardBoot = boot;
})();
