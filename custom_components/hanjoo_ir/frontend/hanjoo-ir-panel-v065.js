import "./hanjoo-ir-panel-base.js";

const PanelClass = customElements.get("hanjoo-ir-panel");
if (PanelClass) {
  const proto = PanelClass.prototype;

  // Show every captured timing instead of truncating the RAW signal preview.
  proto.renderCaptureRecognition = function(cap) {
    const timings = Array.isArray(cap?.timings) ? cap.timings : [];
    const raw = timings.join(" ");
    const freq = Number(cap?.frequency || 0);
    const hint = Array.isArray(cap?.protocol_hints) ? cap.protocol_hints[0] : null;
    const hintText = hint?.protocol
      ? `<br><span>${this.tr("Nhận dạng sơ bộ", "Preliminary")}: <b>${this.esc(hint.brand ? `${hint.brand} ${hint.protocol}` : hint.protocol)}</b> ${Number(hint.confidence || 0)}%</span>`
      : "";
    return `<small class="capture-recognition" style="display:block;white-space:normal;overflow-wrap:anywhere;word-break:break-word"><b>${this.tr("Mã nhận được", "Received code")}:</b> ${freq ? `${Math.round(freq / 1000)} kHz · ` : ""}<span>${this.esc(raw)}</span>${hintText}</small>`;
  };

  const originalRender = proto.render;
  proto.render = function(...args) {
    const result = originalRender.apply(this, args);
    queueMicrotask(() => {
      const root = this.shadowRoot;
      if (!root) return;

      // Recognition-only candidates already get automatic model/profile
      // suggestions below. Remove the duplicate "Find compatible..." button.
      const recognitionIds = new Set(
        (this._identifyResult?.candidates || [])
          .map(row => row?.candidate)
          .filter(candidate => candidate?.recognition_only && candidate?.id)
          .map(candidate => String(candidate.id))
      );
      root.querySelectorAll("[data-identify-add]").forEach(button => {
        if (recognitionIds.has(String(button.dataset.identifyAdd || ""))) button.remove();
      });

      // Search by brand/model should reuse the user's hint when supplied, or
      // otherwise seed the search with the best detected brand + useful model.
      const oldSearch = root.querySelector("[data-identify-search]");
      if (oldSearch && oldSearch.dataset.hanjooV065 !== "1") {
        const search = oldSearch.cloneNode(true);
        search.dataset.hanjooV065 = "1";
        oldSearch.replaceWith(search);
        search.addEventListener("click", () => {
          const best = this._identifyResult?.candidates?.[0]?.candidate || {};
          const model = String(best.model || "").trim();
          const usefulModel = model && !/(^|\s)(family|protocol)(\s|$)/i.test(model) ? model : "";
          this._discoverQuery = String(
            this._identifyQuery || [best.brand, usefulModel].filter(Boolean).join(" ") || ""
          ).trim();
          this._addMode = "search";
          this._discoverLoaded = false;
          this.render();
          setTimeout(() => this.shadowRoot?.querySelector("#discover-search")?.focus(), 0);
        });
      }
    });
    return result;
  };
}
