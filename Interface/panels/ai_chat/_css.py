"""Стили TCSS для панели чата."""

AI_CHAT_PANEL_CSS = """
AIChatPanel {
    height: 1fr;
}
#chat-thread-label {
    dock: top;
    height: 1;
    background: #151520;
    color: #A78BFA;
    text-style: bold;
    padding: 0 1;
}
#chat-log-region {
    height: 1fr;
    min-height: 8;
    border-top: solid #2D2D3D;
    border-bottom: solid #2D2D3D;
}
#main-chat-stream {
    height: 1fr;
    background: #0D0D0D;
    padding: 0 1;
}
#chat-messages-worker {
    height: 1fr;
    background: #0D0D0D;
    padding: 0 1;
}
#attachment-strip {
    height: auto;
    min-height: 1;
    layout: horizontal;
    margin: 0 0 1 0;
    overflow-x: auto;
}
.attach-chip {
    height: auto;
    min-height: 3;
    min-width: 12;
    margin: 0 1 0 0;
    background: #2D2D3D;
    color: #E5E7EB;
    border: solid #3D3D4D;
    text-align: left;
    content-align: left middle;
}
.attach-chip:hover {
    background: #8B5CF6;
}
#deep-status-bar {
    height: 0;
    min-height: 0;
    display: none;
    padding: 0 1;
    margin: 0 0 1 0;
    background: #12121A;
    border-left: thick #8B5CF6;
    color: #E5E7EB;
}
#deep-status-bar.-active {
    height: auto;
    min-height: 1;
    display: block;
}
#ctx-meter-row {
    height: auto;
    min-height: 2;
    layout: horizontal;
    margin: 0 0 1 0;
    padding: 0 0 0 0;
}
#ctx-progress-visual {
    width: 1fr;
    min-width: 18;
    height: auto;
    min-height: 1;
    color: #9CA3AF;
}
#ctx-session-line {
    width: auto;
    min-width: 10;
    height: auto;
    min-height: 1;
    color: #6B7280;
    text-align: right;
    content-align: right middle;
}
#chat-input-area {
    dock: bottom;
    height: auto;
    max-height: 40;
    background: #0D0D0D;
    padding: 0 1 1 1;
}
#creator-progress-slot {
    height: auto;
    width: 100%;
    padding: 0;
    margin: 0 0 1 0;
}
#creator-progress-slot.hidden {
    display: none;
}
#chat-input {
    border: solid #2D2D3D;
    background: #0D0D0D;
    color: #E5E7EB;
}
#chat-controls {
    height: auto;
    layout: horizontal;
    margin-top: 0;
}
#send-btn {
    min-width: 14;
    margin: 0 1 0 0;
}
#attach-file-btn {
    min-width: 16;
    margin: 0 1 0 0;
}
#model-select {
    width: 2fr;
    min-width: 28;
    max-width: 100%;
}
#mode-select {
    width: 1fr;
    min-width: 18;
    max-width: 100%;
    margin: 0 1 0 0;
}
#stop-btn {
    display: none;
}
#stop-btn.visible {
    display: block;
}
#custom-models-line {
    display: none;
}
/* ── Unified settings spacing ──────────────────────────────────
   Every field in every settings tab goes through ``.settings-row`` and
   every button row goes through ``.settings-button-row``. By keeping
   the vertical gap (``margin-bottom: 1``) and padding identical across
   them, the tabs line up visually instead of looking like three
   different screens glued together. Do NOT override these margins in
   per-section CSS — rely on the spacing defined here. */
.settings-row {
    height: auto;
    min-height: 4;
    layout: grid;
    grid-size: 2 1;
    grid-columns: 1fr 2fr;
    grid-gutter: 0 3;
    margin: 0 0 1 0;
    padding: 0 1;
}
.settings-row-label {
    content-align: left middle;
    color: #E5E7EB;
    padding: 1 1;
    min-width: 18;
}
.settings-row Input, .settings-row Select {
    width: 100%;
    min-width: 14;
    height: 3;
}
.settings-row Checkbox {
    width: 100%;
    height: 3;
}
#sor-balance-display {
    height: auto;
    min-height: 3;
    color: #9CA3AF;
    padding: 1 2;
    background: #0D0D12;
    border: tall #2D2D3D;
}
.settings-section-title {
    text-style: bold;
    margin: 1 0 1 0;
    padding: 0 1;
}
.settings-card {
    height: auto;
    padding: 1 2;
    margin: 0 0 1 0;
    background: #12121A;
    border: round #2D2D3D;
}
.settings-card-title {
    text-style: bold;
    margin: 0 0 1 0;
    padding: 0 0 1 0;
}
.settings-card-subtitle {
    color: #6B7280;
    margin: 0 0 1 0;
    padding: 0 1;
    text-style: italic;
}
.settings-hint {
    color: #6B7280;
    margin: 0 0 1 0;
    padding: 0 1;
}
.settings-button-row {
    height: auto;
    layout: horizontal;
    margin: 1 0 0 0;
    padding: 0 1;
}
.settings-button-row Button {
    margin: 0 2 0 0;
    min-width: 24;
    height: 3;
    border: round #2D2D3D;
    padding: 0 2;
    text-style: bold;
}
.settings-action-btn {
    background: #1C1C26;
    color: #E5E7EB;
    border: round #2D2D3D;
}
.settings-action-btn:hover {
    background: #26263A;
}
.settings-action-btn--primary {
    background: #2A1F4D;
    color: #F3F4F6;
}
.settings-action-btn--primary:hover {
    background: #3B2F6B;
}
.settings-action-btn--success {
    background: #10321F;
    color: #A7F3D0;
}
.settings-action-btn--success:hover {
    background: #164C2E;
}
.settings-action-btn--error {
    background: #3A1313;
    color: #FCA5A5;
}
.settings-action-btn--error:hover {
    background: #561E1E;
}
.param-grid {
    height: auto;
    layout: grid;
    grid-size: 2 4;
    grid-rows: 7 7 7 7;
    grid-gutter: 2 3;
    margin: 1 0 1 0;
    padding: 0 1;
}
.param-cell {
    height: 7;
    layout: vertical;
    padding: 1 2;
    background: #0D0D12;
    border: tall #2D2D3D;
}
.param-cell-label {
    text-style: bold;
    height: 1;
}
.param-cell-hint {
    color: #6B7280;
    height: 1;
    text-style: italic;
}
.param-cell Input {
    width: 100%;
    height: 3;
    margin: 1 0;
}
.param-cell-wide {
    column-span: 2;
}
#sol-status {
    color: #9CA3AF;
    margin: 1 0 0 0;
}
#sol-model-list {
    color: #9CA3AF;
    margin: 1 0 0 0;
    padding: 1 2;
    background: #0D0D0D;
    border: solid #2D2D3D;
}
.stream-line {
    height: auto;
    margin: 0 0 0 0;
    color: #9CA3AF;
}
.file-changes-table {
    height: auto;
    padding: 1 2;
    margin: 0 0 1 0;
    background: #12121A;
    border: round #2D2D3D;
}
.sources-widget {
    height: auto;
    padding: 1 2;
    margin: 0 0 1 0;
    background: #12121A;
    border: round #2D2D3D;
}
Collapsible.round-card {
    height: auto;
    margin: 0 0 1 0;
    background: #12121A;
    border: round #2D2D3D;
    padding: 0 0 0 0;
}
Collapsible.round-card > CollapsibleTitle {
    padding: 0 1 0 1;
    height: auto;
    color: #E5E7EB;
}
Collapsible.round-card > Contents {
    padding: 1 1 1 1;
}
"""
