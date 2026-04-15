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
      <main className={styles.main}>
        <h1 className={styles.title}>Minara</h1>
        <p className={styles.lead}>
          Paste a YouTube URL to transcribe (word-level timestamps), then find
          key moments for clips.
        </p>

        <form className={styles.form} onSubmit={onSubmit}>
          <input
            className={styles.input}
            type="url"
            name="youtube_url"
            placeholder="https://www.youtube.com/watch?v=…"
            value={youtubeUrl}
            onChange={(e) => setYoutubeUrl(e.target.value)}
            disabled={loading}
            required
          />
          <button className={styles.button} type="submit" disabled={loading}>
            {loading ? "Transcribing…" : "Transcribe"}
          </button>
        </form>

        {error ? <p className={styles.error}>{error}</p> : null}

        {result ? (
          <section className={styles.results} aria-live="polite">
            <h2>Full transcript</h2>
            <p className={styles.fullText}>{result.text ?? "(no text)"}</p>

            <div className={styles.momentsActions}>
              <button
                type="button"
                className={styles.buttonSecondary}
                onClick={findKeyMoments}
                disabled={momentsLoading || loading}
              >
                {momentsLoading ? "Finding moments…" : "Find Key Moments"}
              </button>
            </div>

            {momentsError ? (
              <p className={styles.error}>{momentsError}</p>
            ) : null}

            {moments && moments.clips && moments.clips.length > 0 ? (
              <div className={styles.momentsSection}>
                <h2>Key moments</h2>
                <ul className={styles.cardList}>
                  {moments.clips.map((clip, i) => (
                    <li key={i} className={styles.card}>
                      <h3 className={styles.cardTitle}>{clip.title}</h3>
                      <p className={styles.cardMeta}>
                        <span>
                          {formatTime(clip.start_time)} –{" "}
                          {formatTime(clip.end_time)}
                        </span>
                        <span className={styles.cardMetaSep}>·</span>
                        <span>{clip.duration.toFixed(1)}s</span>
                        <span className={styles.cardMetaSep}>·</span>
                        <span>
                          Confidence: {clip.confidence_score.toFixed(2)}
                        </span>
                      </p>
                      <p className={styles.cardTakeaway}>
                        <strong>Takeaway:</strong> {clip.takeaway}
                      </p>
                      <p className={styles.cardReason}>
                        <strong>Why:</strong> {clip.reason}
                      </p>
                      <p className={styles.cardExcerpt}>
                        <strong>Excerpt:</strong> {clip.transcript_excerpt}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <h2>Words with timestamps</h2>
            {result.words && result.words.length > 0 ? (
              <div className={styles.words}>
                <div className={`${styles.wordRow} ${styles.wordHeader}`}>
                  <span>Start</span>
                  <span>End</span>
                  <span>Word</span>
                </div>
                {result.words.map((w, i) => (
                  <div key={i} className={styles.wordRow}>
                    <span>{formatTime(w.start)}</span>
                    <span>{formatTime(w.end)}</span>
                    <span>{w.word}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className={styles.muted}>No word-level data in the response.</p>
            )}
          </section>
        ) : null}
      </main>
    </div>
  );
}
