(() => {
    const state = { job: null };
    const form = document.getElementById("analyze-form");
    const input = document.getElementById("media-url");
    const modeInput = document.getElementById("download-mode");
    const qualityInput = document.getElementById("download-quality");
    const analyzeButton = document.getElementById("analyze-button");
    const statusBox = document.getElementById("status-box");
    const resultsPanel = document.getElementById("results-panel");
    const resultsSummary = document.getElementById("results-summary");
    const mediaItems = document.getElementById("media-items");
    const itemTemplate = document.getElementById("item-template");
    const downloadAllButton = document.getElementById("download-all-button");
    const mergeButton = document.getElementById("merge-button");
    const historyList = document.getElementById("history-list");
    const refreshHistoryButton = document.getElementById("refresh-history");

    function showStatus(message, type = "info") { statusBox.hidden = false; statusBox.className = `status-box ${type}`; statusBox.textContent = message; }
    function clearStatus() { statusBox.hidden = true; statusBox.textContent = ""; }
    async function api(url, options = {}) {
        const response = await fetch(url, options);
        const contentType = response.headers.get("content-type") || "";
        const payload = contentType.includes("application/json") ? await response.json() : null;
        if (!response.ok) throw new Error(payload?.error || "تعذر تنفيذ الطلب.");
        return payload;
    }
    function setLoading(isLoading) {
        analyzeButton.disabled = isLoading; input.disabled = isLoading; modeInput.disabled = isLoading; qualityInput.disabled = isLoading;
        analyzeButton.querySelector("span").textContent = isLoading ? "جارٍ تحليل الرابط..." : "تحليل الرابط";
        analyzeButton.classList.toggle("loading", isLoading);
    }
    const itemLabel = (item) => ({ video: "فيديو", audio: "صوت", image: "صورة" }[item.type] || "ملف");
    function summary(job) {
        return `${job.item_count} عنصر • ${job.video_count || 0} فيديو • ${job.audio_count || 0} صوت • ${job.image_count || 0} صورة`;
    }
    function renderJob(job) {
        state.job = job; mediaItems.innerHTML = "";
        resultsSummary.textContent = summary(job);
        downloadAllButton.href = `/api/jobs/${job.id}/download-all`;
        mergeButton.hidden = (job.video_count || 0) < 2;
        job.items.forEach((item) => {
            const node = itemTemplate.content.cloneNode(true);
            node.querySelector(".media-type").textContent = itemLabel(item);
            node.querySelector(".media-order").textContent = String(item.order).padStart(2, "0");
            node.querySelector(".item-title").textContent = item.title || `ملف وسائط ${item.order}`;
            const platform = item.platform ? ` • ${item.platform}` : "";
            node.querySelector(".item-meta").textContent = `${itemLabel(item)} • ${String(item.extension || "").toUpperCase()}${platform}`;
            node.querySelector(".video-symbol").hidden = item.type !== "video";
            node.querySelector(".audio-symbol").hidden = item.type !== "audio";
            node.querySelector(".image-symbol").hidden = item.type !== "image";
            const thumbnail = node.querySelector(".item-thumbnail");
            if (item.thumbnail) { thumbnail.src = item.thumbnail; thumbnail.alt = `معاينة العنصر ${item.order}`; thumbnail.hidden = false; thumbnail.addEventListener("error", () => { thumbnail.hidden = true; }); }
            node.querySelector(".download-item").href = `/api/jobs/${job.id}/download/${item.order}`;
            mediaItems.appendChild(node);
        });
        resultsPanel.hidden = false; resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" }); formatDates();
    }
    async function analyze(event) {
        event.preventDefault(); clearStatus(); setLoading(true); resultsPanel.hidden = true;
        try {
            const body = { url: input.value.trim(), mode: modeInput.value, quality: qualityInput.value };
            const data = await api("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
            renderJob(data.job);
            showStatus(`تم اكتشاف ${data.job.item_count} عنصرًا قابلًا للتنزيل بدون تسجيل دخول.`, "success");
            await loadHistory();
        } catch (error) { showStatus(error.message, "error"); } finally { setLoading(false); }
    }
    async function downloadMerge() {
        if (!state.job) return;
        mergeButton.disabled = true; mergeButton.textContent = "جارٍ تنزيل المقاطع ودمجها..."; showStatus("يتم الآن تجهيز الفيديو النهائي بواسطة FFmpeg.", "info");
        try {
            const response = await fetch(`/api/jobs/${state.job.id}/merge`, { method: "POST" });
            if (!response.ok) { const payload = await response.json().catch(() => ({})); throw new Error(payload.error || "فشل دمج الفيديوهات."); }
            const blob = await response.blob(); const objectUrl = URL.createObjectURL(blob); const link = document.createElement("a");
            link.href = objectUrl; link.download = `media_${state.job.id}_merged.mp4`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(objectUrl);
            showStatus("تم إنشاء الفيديو المدمج بنجاح.", "success"); await loadHistory();
        } catch (error) { showStatus(error.message, "error"); } finally {
            mergeButton.disabled = false; mergeButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg> دمج الفيديوهات';
        }
    }
    function historyRow(job) {
        const row = document.createElement("article"); row.className = "history-row"; row.dataset.jobId = job.id;
        row.innerHTML = `<div class="history-icon"><span>${job.item_count}</span></div><div class="history-copy"><strong></strong><small>${job.video_count || 0} فيديو • ${job.audio_count || 0} صوت • ${job.image_count || 0} صورة</small></div><time datetime="${job.updated_at || ""}" data-iso-date="${job.updated_at || ""}"></time><button class="history-open ghost-button compact" type="button" data-job-id="${job.id}">فتح</button><button class="history-delete icon-button danger" type="button" data-job-id="${job.id}" aria-label="حذف العملية"><svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M9 7V4h6v3m-9 0 1 14h10l1-14"/></svg></button>`;
        row.querySelector("strong").textContent = job.title || "تنزيل وسائط"; return row;
    }
    async function loadHistory() {
        try { const data = await api("/api/history"); historyList.innerHTML = ""; if (!data.history.length) { historyList.innerHTML = '<div class="empty-state">لا توجد عمليات محفوظة بعد.</div>'; return; } data.history.forEach((job) => historyList.appendChild(historyRow(job))); formatDates(); }
        catch (error) { showStatus(error.message, "error"); }
    }
    async function openJob(jobId) { try { const data = await api(`/api/jobs/${jobId}`); renderJob(data.job); input.value = data.job.source_url || ""; showStatus("تم فتح العملية المحفوظة.", "success"); } catch (error) { showStatus(error.message, "error"); } }
    async function deleteJob(jobId) { if (!window.confirm("هل تريد حذف هذه العملية وملفاتها المحلية؟")) return; try { await api(`/api/jobs/${jobId}`, { method: "DELETE" }); if (state.job?.id === jobId) { state.job = null; resultsPanel.hidden = true; } await loadHistory(); showStatus("تم حذف العملية من السجل.", "success"); } catch (error) { showStatus(error.message, "error"); } }
    function formatDates() { document.querySelectorAll("[data-iso-date]").forEach((element) => { const date = new Date(element.dataset.isoDate); if (!Number.isNaN(date.getTime())) element.textContent = new Intl.DateTimeFormat("ar", { dateStyle: "medium", timeStyle: "short" }).format(date); }); }
    modeInput.addEventListener("change", () => { qualityInput.disabled = modeInput.value === "audio"; });
    form.addEventListener("submit", analyze); mergeButton.addEventListener("click", downloadMerge); refreshHistoryButton.addEventListener("click", loadHistory);
    historyList.addEventListener("click", (event) => { const openButton = event.target.closest(".history-open"); const deleteButton = event.target.closest(".history-delete"); if (openButton) openJob(openButton.dataset.jobId); if (deleteButton) deleteJob(deleteButton.dataset.jobId); });
    formatDates();
})();
