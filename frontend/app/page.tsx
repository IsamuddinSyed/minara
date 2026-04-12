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

type TranscribeResult = {
  text?: string;
  words?: WordEntry[];
};

function formatTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(2).padStart(5, "0")}`;
}

export default function Home() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TranscribeResult | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/transcribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtube_url: youtubeUrl.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? data.detail.map((d: { msg?: string }) => d.msg).join("; ")
              : res.statusText;
        throw new Error(msg || `Request failed (${res.status})`);
      }
      setResult(data as TranscribeResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1 className={styles.title}>Minara</h1>
        <p className={styles.lead}>
          Paste a YouTube URL to transcribe with Whisper (word-level timestamps).
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
