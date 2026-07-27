import { useEffect, useRef, useState } from 'react';
import {
  transcriptionApi, type Capabilities, type TranscriptResult,
} from '../features/transcription/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { IconAudio, IconDownload, IconAlert } from '../lib/icons';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

function fmtTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

/**
 * Fully local speech-to-text — whisper.cpp under the hood, nothing leaves
 * the machine. The backend (model download, transcribe) was built and tested
 * earlier in this project; this page is what was missing to actually use it.
 */
export default function Transcribe() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [transcribing, setTranscribing] = useState(false);
  const [result, setResult] = useState<TranscriptResult | null>(null);
  const [fileName, setFileName] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => {
    transcriptionApi.capabilities().then(setCaps).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const downloadModel = async (modelId: string) => {
    setDownloading(modelId);
    try {
      await transcriptionApi.downloadModel(modelId, projectId);
      toast(`${modelId} downloaded`, 'success');
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Download failed', 'error');
    } finally {
      setDownloading(null);
    }
  };

  const removeModel = async (modelId: string) => {
    try {
      await transcriptionApi.deleteModel(modelId);
      toast(`${modelId} removed`, 'success');
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not remove', 'error');
    }
  };

  const onPickFile = async (file: File | undefined) => {
    if (!file) return;
    setFileName(file.name);
    setResult(null);
    setTranscribing(true);
    try {
      const uploaded = await transcriptionApi.uploadAudio(projectId, file);
      const out = await transcriptionApi.transcribe(projectId, uploaded.id);
      setResult(out);
      toast(`Transcribed in ${(out.duration_ms / 1000).toFixed(1)}s`, 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Transcription failed', 'error');
    } finally {
      setTranscribing(false);
    }
  };

  const copyTranscript = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.text);
      toast('Copied to clipboard', 'success');
    } catch {
      toast('Could not copy', 'error');
    }
  };

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  return (
    <div>
      <PageHeader
        title="Transcribe"
        subtitle="Local, offline speech-to-text — audio never leaves this machine."
      />

      {!caps?.ready && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/5 px-4 py-2.5 text-[12px] text-ink-muted">
          <IconAlert size={15} className="mt-px shrink-0 text-warning" />
          <span>{caps?.reason || 'Not ready yet — download a model below.'}</span>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        {/* Models */}
        <Card>
          <CardBody>
            <h3 className="mb-1 text-sm font-semibold text-ink">Models</h3>
            <p className="mb-3 text-[12px] text-ink-muted">
              Downloaded once, then fully offline. {caps?.whisper_cli ? 'Using whisper.cpp.'
                : caps?.faster_whisper ? 'Using faster-whisper.' : ''}
            </p>
            <ul className="space-y-2">
              {caps?.available_models.map((m) => {
                const installed = caps.models.some((i) => i.id === m.id);
                return (
                  <li key={m.id} className="rounded-xl border border-line px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium text-ink">{m.id}</span>
                      {installed ? (
                        <Badge tone="success">installed</Badge>
                      ) : (
                        <Button variant="ghost" icon={<IconDownload size={13} />}
                                loading={downloading === m.id}
                                onClick={() => downloadModel(m.id)}>
                          {m.size_mb} MB
                        </Button>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11px] text-ink-muted">{m.blurb}</p>
                    {installed && (
                      <button onClick={() => removeModel(m.id)}
                              className="mt-1 text-[11px] text-danger hover:underline">
                        Remove
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
            {!caps?.ffmpeg && (
              <p className="mt-3 text-[11px] text-warning">
                ffmpeg not found — needed to convert most audio formats. Install with{' '}
                <code className="rounded bg-surface2 px-1 py-px">brew install ffmpeg</code>.
              </p>
            )}
          </CardBody>
        </Card>

        {/* Transcript */}
        <Card className="overflow-hidden">
          <div className="border-b border-line px-5 py-3">
            <input
              ref={fileRef}
              type="file"
              accept="audio/*,video/*"
              className="hidden"
              onChange={(e) => onPickFile(e.target.files?.[0])}
            />
            <Button
              variant="primary"
              icon={<IconAudio size={15} />}
              loading={transcribing}
              disabled={!caps?.ready}
              onClick={() => fileRef.current?.click()}
            >
              {transcribing ? 'Transcribing…' : 'Choose an audio file'}
            </Button>
            {fileName && !transcribing && (
              <span className="ml-2 text-[12px] text-ink-muted">{fileName}</span>
            )}
          </div>

          {!result ? (
            <EmptyState
              icon={<IconAudio size={22} />}
              title="Nothing transcribed yet"
              description="Drop in a voice memo, meeting recording, or any audio file — you'll get plain text back, generated entirely on this machine."
            />
          ) : (
            <CardBody>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
                <Badge tone="neutral">{result.engine}</Badge>
                <span>{result.model}</span>
                <span>· {fmtTime(result.audio_seconds)} audio</span>
                <span>· {(result.duration_ms / 1000).toFixed(1)}s to transcribe</span>
                <Button variant="ghost" className="ml-auto" onClick={copyTranscript}>
                  Copy text
                </Button>
              </div>
              <div className="max-h-[50vh] space-y-2 overflow-y-auto">
                {result.segments.map((s, i) => (
                  <div key={i} className="flex gap-3 text-[13px]">
                    <span className="mt-0.5 shrink-0 font-mono text-[11px] text-ink-muted">
                      {fmtTime(s.start)}
                    </span>
                    <span className="text-ink">{s.text}</span>
                  </div>
                ))}
              </div>
            </CardBody>
          )}
        </Card>
      </div>
    </div>
  );
}
