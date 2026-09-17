import "./hanjoo-ir-panel-base.js";

const PanelClass = customElements.get("hanjoo-ir-panel");
if (PanelClass) {
  const proto = PanelClass.prototype;

  // Three distinct captures are enough for the current Fusion safety rules.
  // For A/C, 24 -> 25 -> 26 C preserves state/checksum changes without asking
  // for a fourth Power Off press.
  proto.identifySteps = function() {
    if (this._identifyKind === "air_conditioner") return [
      { label: "Cool 24°C", help: this.tr("Đặt remote ở Cool 23°C, sau đó bấm Temp+ một lần để phát Cool 24°C.", "Prepare the remote at Cool 23°C, then press Temp+ once to send Cool 24°C."), expected: { power: true, mode: "cool", temp: 24 } },
      { label: "Cool 25°C", help: this.tr("Từ 24°C, bấm Temp+ một lần để phát Cool 25°C.", "From 24°C, press Temp+ once to send Cool 25°C."), expected: { power: true, mode: "cool", temp: 25 } },
      { label: "Cool 26°C", help: this.tr("Từ 25°C, bấm Temp+ một lần để phát Cool 26°C.", "From 25°C, press Temp+ once to send Cool 26°C."), expected: { power: true, mode: "cool", temp: 26 } },
    ];
    const byKind = {
      tv: ["Power", "Volume +", "Mute"],
      fan: ["Power", "Speed", "Oscillate / Swing"],
      projector: ["Power", "Input / Source", "Menu"],
      speaker: ["Power", "Volume +", "Mute"],
    };
    const labels = byKind[this._identifyKind] || [
      "Power",
      this.tr("Nút chức năng thứ hai", "Second function button"),
      this.tr("Nút chức năng thứ ba", "Third function button"),
    ];
    return [
      { label: labels[0], help: this.tr(`Khi HanJoo chờ bước 1, nhấn ${labels[0]} trên remote.`, `When HanJoo waits for step 1, press ${labels[0]} on the remote.`), expected: {} },
      { label: labels[1], help: this.tr(`HanJoo tự chuyển sang bước 2; nhấn ${labels[1]}.`, `HanJoo moves to step 2 automatically; press ${labels[1]}.`), expected: {} },
      { label: labels[2], help: this.tr(`HanJoo tự chuyển sang bước 3; nhấn ${labels[2]}.`, `HanJoo moves to step 3 automatically; press ${labels[2]}.`), expected: {} },
    ];
  };

  // Keep RAW diagnostics available, but collapse the long timing string by
  // default so each captured sample stays only one compact row high.
  proto.renderCaptureRecognition = function(cap) {
    const timings = Array.isArray(cap?.timings) ? cap.timings : [];
    const raw = timings.join(" ");
    const freq = Number(cap?.frequency || 0);
    const hint = Array.isArray(cap?.protocol_hints) ? cap.protocol_hints[0] : null;
    const hintText = hint?.protocol
      ? `<div style="margin-top:6px">${this.tr("Nhận dạng sơ bộ", "Preliminary")}: <b>${this.esc(hint.brand ? `${hint.brand} ${hint.protocol}` : hint.protocol)}</b> ${Number(hint.confidence || 0)}%</div>`
      : "";
    return `<div class="capture-code-compact" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:5px">
      <span style="color:var(--secondary-text-color)"><b>${this.tr("Mã nhận được", "Received code")}</b>${freq ? ` · ${Math.round(freq / 1000)} kHz` : ""}</span>
      <details class="capture-code-details" style="display:inline-block">
        <summary style="cursor:pointer;display:inline-flex;align-items:center;padding:4px 9px;border:1px solid var(--divider-color);border-radius:8px;color:var(--primary-text-color);list-style:none">${this.tr("Xem", "View")}</summary>
        <div class="mono" style="margin-top:7px;padding:9px;border-radius:8px;background:var(--secondary-background-color);white-space:normal;overflow-wrap:anywhere;word-break:break-word;max-height:220px;overflow:auto"><b>${this.tr("Mã nhận được", "Received code")}:</b> ${this.esc(raw)}${hintText}</div>
      </details>
    </div>`;
  };

  const originalRender = proto.render;
  proto.render = function(...args) {
    const result = originalRender.apply(this, args);
    queueMicrotask(() => {
      const root = this.shadowRoot;
      if (!root) return;

      // Recognition-only results are evidence, not directly addable devices.
      const recognitionIds = new Set(
        (this._identifyResult?.candidates || [])
          .map(row => row?.candidate)
          .filter(candidate => candidate?.recognition_only && candidate?.id)
          .map(candidate => String(candidate.id))
      );
      root.querySelectorAll("[data-identify-add]").forEach(button => {
        if (recognitionIds.has(String(button.dataset.identifyAdd || ""))) button.remove();
      });

      // Keep the three primary actions on one line in both VI and EN:
      // Start/Continue | Clear | Analyze again.
      const actionBar = root.querySelector(".identify-start-actions");
      const reset = root.querySelector("#identify-reset");
      if (reset) reset.textContent = this.tr("Xóa", "Clear");
      const analyze = root.querySelector("#identify-analyze");
      if (actionBar && analyze && analyze.parentElement !== actionBar) {
        analyze.remove();
        actionBar.appendChild(analyze);
      }
      if (actionBar) {
        actionBar.style.justifyContent = "flex-end";
        actionBar.style.alignItems = "center";
      }

      // Search by brand/model reuses the user's hint, or the best useful hint.
      const oldSearch = root.querySelector("[data-identify-search]");
      if (oldSearch && oldSearch.dataset.hanjooV065 !== "1") {
        const search = oldSearch.cloneNode(true);
        search.dataset.hanjooV065 = "1";
        oldSearch.replaceWith(search);
        search.addEventListener("click", () => {
          const best = this._identifyResult?.candidates?.[0]?.candidate || {};
          const model = String(best.model || "").trim();
          const usefulModel = model && !/(^|\s)(family|protocol)(\s|$)/i.test(model) ? model : "";
          this._discoverQuery = String(this._identifyQuery || [best.brand, usefulModel].filter(Boolean).join(" ") || "").trim();
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
