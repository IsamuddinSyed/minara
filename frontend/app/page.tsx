"use client";

import { FormEvent, useState } from "react";
import styles from "./page.module.css";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type WordEntry = {
  word: string;
  start: number;
  end: number;
};

/** Matches POST /transcribe response; sent verbatim to /identify-moments */
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TranscriptPayload | null>(null);

  const [momentsLoading, setMomentsLoading] = useState(false);
  const [momentsError, setMomentsError] = useState<string | null>(null);
  const [moments, setMoments] = useState<MomentsResult | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setMoments(null);
    setMomentsError(null);
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
    } catch (err) {
      setMomentsError(
        err instanceof Error ? err.message : "Something went wrong",
      );
    } finally {
      setMomentsLoading(false);
    }
  }

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
            <h1 className={styles.brandName}>Minara</h1>
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
            </div>

            <div className={styles.noteCard}>
              <p className={styles.noteTitle}>Workflow</p>
              <p className={styles.noteText}>
                Start with transcription, review the timed transcript, then
                generate clip candidates for reels and shorts.
              </p>
            </div>
          </div>
        </section>

        <section className={styles.resultsColumn} aria-live="polite">
          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.kicker}>Transcript</p>
                <h2 className={styles.panelTitle}>Transcript Review</h2>
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

            {result ? (
              <div className={styles.transcriptLayout}>
                <div className={styles.transcriptSummary}>
                  <p className={styles.summaryLabel}>Full transcript</p>
                  <p className={styles.summaryText}>
                    {result.text ?? "(no text)"}
                  </p>
                </div>

                {result.words && result.words.length > 0 ? (
                  <div className={styles.transcriptPanel}>
                    <div
                      className={`${styles.wordRow} ${styles.wordHeader}`}
                    >
                      <span>Start</span>
                      <span>End</span>
                      <span>Word</span>
                    </div>
                    <div className={styles.wordRows}>
                      {result.words.map((w, i) => (
                        <div key={i} className={styles.wordRow}>
                          <span className={styles.timestamp}>
                            {formatTime(w.start)}
                          </span>
                          <span className={styles.timestamp}>
                            {formatTime(w.end)}
                          </span>
                          <span className={styles.wordText}>{w.word}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className={styles.emptyStateCompact}>
                    <div className={styles.emptyMotif} aria-hidden="true" />
                    <p className={styles.emptyTitle}>No transcript data yet</p>
                    <p className={styles.emptyText}>
                      Word-level timestamps will appear here after
                      transcription.
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className={styles.emptyState}>
                <div className={styles.emptyMotif} aria-hidden="true" />
                <p className={styles.emptyTitle}>Paste a YouTube link to begin</p>
                <p className={styles.emptyText}>
                  Your transcript timeline will appear here once audio has been
                  processed.
                </p>
              </div>
            )}
          </div>

          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.kicker}>Moments</p>
                <h2 className={styles.panelTitle}>Clip Candidates</h2>
              </div>
            </div>

            {moments && moments.clips && moments.clips.length > 0 ? (
              <ul className={styles.cardList}>
                {moments.clips.map((clip, i) => (
                  <li key={i} className={styles.momentCard}>
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
                ))}
              </ul>
            ) : (
              <div className={styles.emptyState}>
                <div className={styles.emptyMotif} aria-hidden="true" />
                <p className={styles.emptyTitle}>No moments identified yet</p>
                <p className={styles.emptyText}>
                  Generate key moments after transcription to review standout
                  clips here.
                </p>
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
