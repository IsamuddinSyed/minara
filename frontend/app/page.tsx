"use client";

import { FormEvent, useState } from "react";
import styles from "./page.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type WordEntry = {
  word: string;
  start: number;
  end: number;
};

type TranscriptPayload = {
  text: string;
  words: WordEntry[];
  task?: string;
  language?: string;
  duration?: number;
  segments?: unknown[];
};

type Clip = {
  start_time: number;
  end_time: number;
  duration: number;
  title: string;
  takeaway: string;
  reason: string;
  confidence_score: number;
  transcript_excerpt: string;
};

type MomentsResult = {
  clips: Clip[];
};

type GeneratedClip = {
  clip_id: string;
  video_id: string;
  start_time: number;
  end_time: number;
  duration: number;
  title: string;
  takeaway: string;
  reason: string;
  raw_file_path: string;
  raw_preview_url: string;
  processed_file_path?: string | null;
  processed_preview_url?: string | null;
  width?: number | null;
  height?: number | null;
  preview_url: string;
};

type GeneratedClipError = {
  clip_id: string;
  rank: number;
  title: string;
  detail: string;
};

type GeneratedClipsResult = {
  video_id: string;
  source_title: string;
  source_video_path: string;
  source_duration?: number;
  clips: GeneratedClip[];
  errors: GeneratedClipError[];
};

type ViewTab = "transcript" | "words" | "moments" | "clips";

const VIEW_TABS: Array<{ id: ViewTab; label: string }> = [
  { id: "transcript", label: "Transcript" },
  { id: "words", label: "Word by Word" },
  { id: "moments", label: "Key Moments" },
  { id: "clips", label: "Clips" },
];

function formatTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(2).padStart(5, "0")}`;
}

function parseErrorDetail(data: unknown, fallback: string): string {
  if (typeof data !== "object" || data === null) return fallback;
  const d = data as Record<string, unknown>;
  if (typeof d.detail === "string") return d.detail;
  if (Array.isArray(d.detail)) {
    return d.detail
      .map((item) =>
        typeof item === "object" &&
        item !== null &&
        "msg" in item &&
        typeof (item as { msg: unknown }).msg === "string"
          ? (item as { msg: string }).msg
          : String(item),
      )
      .join("; ");
  }
  return fallback;
}

function formatDuration(seconds?: number): string {
  if (!seconds || Number.isNaN(seconds)) return "Unknown";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

export default function Home() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [activeView, setActiveView] = useState<ViewTab>("moments");
  const [selectedMomentIndexes, setSelectedMomentIndexes] = useState<number[]>(
    [],
  );

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TranscriptPayload | null>(null);

  const [momentsLoading, setMomentsLoading] = useState(false);
  const [momentsError, setMomentsError] = useState<string | null>(null);
  const [moments, setMoments] = useState<MomentsResult | null>(null);

  const [clipsLoading, setClipsLoading] = useState(false);
  const [clipsError, setClipsError] = useState<string | null>(null);
  const [generatedClips, setGeneratedClips] =
    useState<GeneratedClipsResult | null>(null);

  function resetClipSelection() {
    setSelectedMomentIndexes([]);
  }

  function toggleMomentSelection(index: number) {
    setSelectedMomentIndexes((current) =>
      current.includes(index)
        ? current.filter((item) => item !== index)
        : [...current, index].sort((a, b) => a - b),
    );
  }

  function selectAllMoments() {
    setSelectedMomentIndexes(
      moments?.clips?.map((_, index) => index) ?? [],
    );
  }

  function clearMomentSelection() {
    setSelectedMomentIndexes([]);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setMoments(null);
    setMomentsError(null);
    setGeneratedClips(null);
    setClipsError(null);
    resetClipSelection();
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/transcribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtube_url: youtubeUrl.trim() }),
      });
      const data: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          parseErrorDetail(data, res.statusText || `Request failed (${res.status})`),
        );
      }
      setResult(data as TranscriptPayload);
      setActiveView("transcript");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  async function findKeyMoments() {
    if (!result) return;
    setMomentsError(null);
    setMoments(null);
    setGeneratedClips(null);
    setClipsError(null);
    resetClipSelection();
    setMomentsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/identify-moments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(result),
      });
      const data: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          parseErrorDetail(data, res.statusText || `Request failed (${res.status})`),
        );
      }
      setMoments(data as MomentsResult);
      setActiveView("moments");
    } catch (err) {
      setMomentsError(
        err instanceof Error ? err.message : "Something went wrong",
      );
    } finally {
      setMomentsLoading(false);
    }
  }

  async function generatePreviewClips() {
    const selectedMoments =
      moments?.clips?.filter((_, index) => selectedMomentIndexes.includes(index)) ??
      [];
    if (!selectedMoments.length) {
      setClipsError("Select at least one key moment before generating clips.");
      setActiveView("moments");
      return;
    }

    setClipsError(null);
    setGeneratedClips(null);
    setClipsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/generate-clips`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          youtube_url: youtubeUrl.trim(),
          transcript_words: result?.words ?? [],
          moments: selectedMoments.map((clip, index) => ({
            rank: selectedMomentIndexes[index] + 1,
            start_time: clip.start_time,
            end_time: clip.end_time,
            title: clip.title,
            takeaway: clip.takeaway,
            reason: clip.reason,
          })),
        }),
      });
      const data: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          parseErrorDetail(data, res.statusText || `Request failed (${res.status})`),
        );
      }
      const generated = data as GeneratedClipsResult;
      console.info(
        "Minara clip previews",
        generated.clips.map((clip) => ({
          clipId: clip.clip_id,
          previewSource: clip.processed_preview_url ? "processed" : "raw",
          previewUrl: clip.preview_url,
          width: clip.width,
          height: clip.height,
        })),
      );
      setGeneratedClips(generated);
      setActiveView("clips");
    } catch (err) {
      setClipsError(
        err instanceof Error ? err.message : "Something went wrong",
      );
    } finally {
      setClipsLoading(false);
    }
  }

  const selectedMomentsCount = selectedMomentIndexes.length;

  return (
    <div className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.brandBlock}>
          <div className={styles.brandMark} aria-hidden="true">
            <span />
            <span />
          </div>
          <div>
            <p className={styles.brandEyebrow}>AI clipping studio</p>
            <h1 className={styles.brandName}>minara.ai</h1>
          </div>
        </div>
        <p className={styles.topbarCopy}>
          Turn long Islamic lectures into short-form moments with transcript-led
          review.
        </p>
      </header>

      <main className={styles.dashboard}>
        <section className={styles.controlsColumn}>
          <div className={styles.controlCard}>
            <div className={styles.sectionIntro}>
              <p className={styles.kicker}>Input</p>
              <h2 className={styles.sectionTitle}>Paste YouTube URL</h2>
              <p className={styles.sectionText}>
                Submit a lecture or khutbah link to generate a timed transcript,
                then surface clip-worthy moments.
              </p>
            </div>

            <form className={styles.form} onSubmit={onSubmit}>
              <label className={styles.label} htmlFor="youtube-url">
                YouTube link
              </label>
              <input
                id="youtube-url"
                className={styles.input}
                type="url"
                name="youtube_url"
                placeholder="https://www.youtube.com/watch?v=..."
                value={youtubeUrl}
                onChange={(e) => setYoutubeUrl(e.target.value)}
                disabled={loading}
                required
              />

              <div className={styles.buttonGroup}>
                <button
                  className={styles.buttonPrimary}
                  type="submit"
                  disabled={loading}
                >
                  {loading ? (
                    <span className={styles.buttonContent}>
                      <span className={styles.spinner} aria-hidden="true" />
                      Transcribing...
                    </span>
                  ) : (
                    "Transcribe"
                  )}
                </button>

                <button
                  type="button"
                  className={styles.buttonSecondary}
                  onClick={findKeyMoments}
                  disabled={!result || momentsLoading || loading}
                >
                  {momentsLoading ? (
                    <span className={styles.buttonContent}>
                      <span className={styles.spinner} aria-hidden="true" />
                      Analyzing moments...
                    </span>
                  ) : (
                    "Find Key Moments"
                  )}
                </button>
              </div>
            </form>

            {error ? <p className={styles.error}>{error}</p> : null}
            {momentsError ? <p className={styles.error}>{momentsError}</p> : null}
            {clipsError ? <p className={styles.error}>{clipsError}</p> : null}

            <div className={styles.statusPanel}>
              <div className={styles.statusRow}>
                <span className={styles.statusLabel}>Transcript</span>
                <span className={styles.statusValue}>
                  {loading
                    ? "Processing..."
                    : result
                      ? `${result.words.length} words captured`
                      : "Awaiting input"}
                </span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusLabel}>Moments</span>
                <span className={styles.statusValue}>
                  {momentsLoading
                    ? "Analyzing..."
                    : moments?.clips?.length
                      ? `${moments.clips.length} clips identified`
                      : "No moments yet"}
                </span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusLabel}>Selected</span>
                <span className={styles.statusValue}>
                  {selectedMomentsCount
                    ? `${selectedMomentsCount} chosen`
                    : "None selected"}
                </span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusLabel}>Previews</span>
                <span className={styles.statusValue}>
                  {clipsLoading
                    ? "Generating..."
                    : generatedClips?.clips?.length
                      ? `${generatedClips.clips.length} previews ready`
                      : "No previews yet"}
                </span>
              </div>
            </div>

            <div className={styles.noteCard}>
              <p className={styles.noteTitle}>Workflow</p>
              <p className={styles.noteText}>
                Transcribe first, review key moments, choose the strongest ones,
                then generate only the clips you want to preview.
              </p>
            </div>
          </div>
        </section>

        <section className={styles.resultsColumn} aria-live="polite">
          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.kicker}>Workspace</p>
                <h2 className={styles.panelTitle}>Review and Generate</h2>
              </div>
              {result ? (
                <div className={styles.metaGroup}>
                  <span className={styles.metaChip}>
                    {formatDuration(result.duration)}
                  </span>
                  <span className={styles.metaChip}>
                    {result.language?.toUpperCase() || "Unknown language"}
                  </span>
                </div>
              ) : null}
            </div>

            <div className={styles.viewTabs} role="tablist" aria-label="Content view">
              {VIEW_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={activeView === tab.id}
                  className={
                    activeView === tab.id ? styles.viewTabActive : styles.viewTab
                  }
                  onClick={() => setActiveView(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {activeView === "transcript" ? (
              result ? (
                <div className={styles.focusSection}>
                  <div className={styles.transcriptSummary}>
                    <p className={styles.summaryLabel}>Full transcript</p>
                    <p className={styles.summaryText}>{result.text ?? "(no text)"}</p>
                  </div>
                </div>
              ) : (
                <div className={styles.emptyState}>
                  <div className={styles.emptyMotif} aria-hidden="true" />
                  <p className={styles.emptyTitle}>Paste a YouTube link to begin</p>
                  <p className={styles.emptyText}>
                    Your transcript will appear here once transcription finishes.
                  </p>
                </div>
              )
            ) : null}

            {activeView === "words" ? (
              result?.words?.length ? (
                <div className={styles.focusSection}>
                  <div className={styles.transcriptPanel}>
                    <div className={`${styles.wordRow} ${styles.wordHeader}`}>
                      <span>Start</span>
                      <span>End</span>
                      <span>Word</span>
                    </div>
                    <div className={styles.wordRows}>
                      {result.words.map((w, i) => (
                        <div key={i} className={styles.wordRow}>
                          <span className={styles.timestamp}>{formatTime(w.start)}</span>
                          <span className={styles.timestamp}>{formatTime(w.end)}</span>
                          <span className={styles.wordText}>{w.word}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className={styles.emptyState}>
                  <div className={styles.emptyMotif} aria-hidden="true" />
                  <p className={styles.emptyTitle}>No word-by-word data yet</p>
                  <p className={styles.emptyText}>
                    Run transcription to review the timed word list here.
                  </p>
                </div>
              )
            ) : null}

            {activeView === "moments" ? (
              moments?.clips?.length ? (
                <div className={styles.focusSection}>
                  <div className={styles.momentsToolbar}>
                    <p className={styles.selectionSummary}>
                      {selectedMomentsCount
                        ? `${selectedMomentsCount} moment${selectedMomentsCount === 1 ? "" : "s"} selected`
                        : "Select one or more moments to generate clips"}
                    </p>
                    <div className={styles.selectionActions}>
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={selectAllMoments}
                        disabled={!moments.clips.length}
                      >
                        Select all
                      </button>
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={clearMomentSelection}
                        disabled={!selectedMomentsCount}
                      >
                        Clear
                      </button>
                      <button
                        type="button"
                        className={styles.inlineActionStrong}
                        onClick={generatePreviewClips}
                        disabled={clipsLoading || loading || momentsLoading}
                      >
                        {clipsLoading ? (
                          <span className={styles.buttonContent}>
                            <span className={styles.spinner} aria-hidden="true" />
                            Generating clips...
                          </span>
                        ) : (
                          "Generate Clips"
                        )}
                      </button>
                    </div>
                  </div>

                  <ul className={styles.cardList}>
                    {moments.clips.map((clip, index) => {
                      const isSelected = selectedMomentIndexes.includes(index);
                      return (
                        <li
                          key={`${clip.title}-${index}`}
                          className={
                            isSelected
                              ? styles.momentCardSelected
                              : styles.momentCard
                          }
                        >
                          <label className={styles.selectionControl}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleMomentSelection(index)}
                            />
                            <span>Select</span>
                          </label>
                          <div className={styles.cardWatermark} aria-hidden="true" />
                          <div className={styles.cardHeader}>
                            <h3 className={styles.cardTitle}>{clip.title}</h3>
                            <span className={styles.confidenceBadge}>
                              {Math.round(clip.confidence_score * 100)}% confidence
                            </span>
                          </div>
                          <p className={styles.cardTakeaway}>{clip.takeaway}</p>
                          <div className={styles.cardStats}>
                            <span>{clip.duration.toFixed(1)}s</span>
                            <span>{formatTime(clip.start_time)}</span>
                            <span>{formatTime(clip.end_time)}</span>
                          </div>
                          <p className={styles.cardReason}>{clip.reason}</p>
                          <p className={styles.cardExcerpt}>{clip.transcript_excerpt}</p>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ) : (
                <div className={styles.emptyState}>
                  <div className={styles.emptyMotif} aria-hidden="true" />
                  <p className={styles.emptyTitle}>No moments identified yet</p>
                  <p className={styles.emptyText}>
                    Generate key moments after transcription to choose which clips
                    you want to create.
                  </p>
                </div>
              )
            ) : null}

            {activeView === "clips" ? (
              generatedClips?.clips?.length ? (
                <div className={styles.previewList}>
                  {generatedClips.clips.map((clip) => (
                    <article key={clip.clip_id} className={styles.previewCard}>
                      <div className={styles.previewHeader}>
                        <div>
                          <h3 className={styles.previewTitle}>{clip.title}</h3>
                          <p className={styles.previewTakeaway}>{clip.takeaway}</p>
                        </div>
                        <div className={styles.previewHeaderMeta}>
                          <span className={styles.metaChip}>
                            {formatDuration(clip.duration)}
                          </span>
                          <span className={styles.metaChip}>
                            {clip.processed_preview_url ? "Processed" : "Raw"}
                          </span>
                        </div>
                      </div>
                      <video
                        className={styles.previewVideo}
                        controls
                        preload="metadata"
                        src={`${API_BASE}${clip.preview_url}`}
                      />
                      <div className={styles.previewMeta}>
                        <span>{formatTime(clip.start_time)}</span>
                        <span>{formatTime(clip.end_time)}</span>
                        <span>{clip.video_id}</span>
                        {clip.width && clip.height ? (
                          <span>
                            {clip.width}x{clip.height}
                          </span>
                        ) : null}
                      </div>
                      <p className={styles.previewReason}>{clip.reason}</p>
                    </article>
                  ))}

                  {generatedClips.errors.length > 0 ? (
                    <div className={styles.partialErrors}>
                      <p className={styles.partialErrorsTitle}>
                        Some clips could not be generated
                      </p>
                      <ul className={styles.errorList}>
                        {generatedClips.errors.map((item) => (
                          <li key={item.clip_id}>
                            <strong>{item.title}:</strong> {item.detail}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className={styles.previewList}>
                  <div className={styles.emptyState}>
                    <div className={styles.emptyMotif} aria-hidden="true" />
                    <p className={styles.emptyTitle}>No clips generated yet</p>
                    <p className={styles.emptyText}>
                      Choose moments in the Key Moments view, then generate clips to
                      preview them here.
                    </p>
                  </div>

                  {generatedClips?.errors?.length ? (
                    <div className={styles.partialErrors}>
                      <p className={styles.partialErrorsTitle}>
                        Clip generation did not complete
                      </p>
                      <ul className={styles.errorList}>
                        {generatedClips.errors.map((item) => (
                          <li key={item.clip_id}>
                            <strong>{item.title}:</strong> {item.detail}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              )
            ) : null}
          </div>
        </section>
      </main>
    </div>
  );
}
