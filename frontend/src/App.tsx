import { useCallback, useState } from "react";
import { ReceiptCard } from "./components/ReceiptCard";
import {
  uploadReceiptImage,
  submitComplete,
  getStatus,
} from "./api/receipts";
import type { ReceiptEntry, ReceiptMetadata } from "./types";

function generateId() {
  return crypto.randomUUID?.() ?? `id-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

const createEmptyEntry = (): ReceiptEntry => ({
  id: generateId(),
  image: null,
  previewUrl: null,
  objectKey: "",
  receiptId: null,
  metadata: {
    payDate: "",
    amount: 0,
    cardPrefix: "",
  },
  status: "IDLE",
});

export default function App() {
  const [receiptEntries, setReceiptEntries] = useState<ReceiptEntry[]>(() => [
    createEmptyEntry(),
  ]);
  const [type, setType] = useState<"STAY" | "TOUR">("TOUR");
  const [userUuid] = useState(() =>
    localStorage.getItem("gems_user_uuid") ?? `user-${generateId()}`
  );
  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<
    { receiptId: string; status?: string; failReason?: string }[] | null
  >(null);

  const setEntry = useCallback((id: string, updater: (e: ReceiptEntry) => ReceiptEntry) => {
    setReceiptEntries((prev) =>
      prev.map((e) => (e.id === id ? updater(e) : e))
    );
  }, []);

  const addEntry = useCallback(() => {
    setReceiptEntries((prev) => [...prev, createEmptyEntry()]);
  }, []);

  const removeEntry = useCallback((id: string) => {
    setReceiptEntries((prev) => {
      const next = prev.filter((e) => e.id !== id);
      return next.length ? next : [createEmptyEntry()];
    });
  }, []);

  const onImageSelect = useCallback(
    async (id: string, file: File) => {
      setEntry(id, (e) => ({
        ...e,
        image: file,
        previewUrl: URL.createObjectURL(file),
        status: "UPLOADING",
        errorMessage: undefined,
      }));

      try {
        const { receiptId, objectKey } = await uploadReceiptImage(
          file,
          userUuid,
          type
        );
        setEntry(id, (e) => ({
          ...e,
          receiptId,
          objectKey,
          status: "COMPLETE",
        }));
      } catch (err) {
        const msg = err instanceof Error ? err.message : "업로드 실패";
        setEntry(id, (e) => ({
          ...e,
          status: "ERROR",
          errorMessage: msg,
        }));
      }
    },
    [type, userUuid, setEntry]
  );

  const onMetadataChange = useCallback(
    (id: string, metadata: Partial<ReceiptMetadata>) => {
      setEntry(id, (e) => ({
        ...e,
        metadata: { ...e.metadata, ...metadata },
      }));
    },
    [setEntry]
  );

  /** 동적 유효성: STAY=location 필수, TOUR=storeName 필수 */
  const validateEntries = useCallback((): boolean => {
    for (const e of receiptEntries) {
      if (e.status !== "COMPLETE" || !e.receiptId || !e.objectKey) {
        alert("모든 영수증 이미지를 업로드해 주세요.");
        return false;
      }
      const m = e.metadata;
      if (!m.payDate?.trim() || m.amount <= 0 || !m.cardPrefix?.trim()) {
        alert("결제일, 금액, 카드 앞 4자리를 모두 입력해 주세요.");
        return false;
      }
      if (type === "STAY" && !m.location?.trim()) {
        alert("숙박은 소재지(시군)를 입력해 주세요.");
        return false;
      }
      if (type === "TOUR" && !m.storeName?.trim()) {
        alert("관광은 상호명을 입력해 주세요.");
        return false;
      }
    }
    return true;
  }, [receiptEntries, type]);

  const onSubmit = useCallback(async () => {
    if (!validateEntries()) return;

    const toSubmit = receiptEntries.filter(
      (e) => e.status === "COMPLETE" && e.receiptId && e.objectKey
    );
    if (!toSubmit.length) return;

    setSubmitting(true);
    setSubmitResult(null);

    const results: { receiptId: string; status?: string; failReason?: string }[] = [];

    try {
      for (const entry of toSubmit) {
        const data =
          type === "STAY"
            ? {
                location: entry.metadata.location ?? "",
                payDate: entry.metadata.payDate,
                amount: entry.metadata.amount,
                cardPrefix: entry.metadata.cardPrefix,
                receiptImageKey: entry.objectKey,
                isOta: false,
              }
            : {
                storeName: entry.metadata.storeName ?? "",
                payDate: entry.metadata.payDate,
                amount: entry.metadata.amount,
                cardPrefix: entry.metadata.cardPrefix,
                receiptImageKeys: [entry.objectKey],
              };

        const res = await submitComplete(
          entry.receiptId!,
          userUuid,
          type,
          data,
          1
        );
        results.push({ receiptId: res.receiptId });

        const statusRes = await pollStatus(res.receiptId);
        const last = results[results.length - 1];
        if (last) {
          last.status = statusRes.status ?? undefined;
          last.failReason = statusRes.failReason ?? undefined;
        }
      }
      setSubmitResult(results);
    } catch (err) {
      alert(err instanceof Error ? err.message : "제출 실패");
    } finally {
      setSubmitting(false);
    }
  }, [receiptEntries, type, userUuid, validateEntries]);

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8 print:hidden">
      <div className="mx-auto max-w-2xl">
        <header className="mb-8">
          <h1 className="text-xl font-bold text-slate-800">
            2026 혜택받go 강원 여행 인센티브
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            영수증을 업로드하고 정보를 입력한 뒤 제출하세요.
          </p>
        </header>

        <div className="mb-6 rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
          <label className="block text-sm font-medium text-slate-600">
            유형
          </label>
          <div className="mt-2 flex gap-4">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="type"
                checked={type === "STAY"}
                onChange={() => setType("STAY")}
                className="h-4 w-4 text-primary focus:ring-primary"
              />
              <span>숙박 (STAY)</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="type"
                checked={type === "TOUR"}
                onChange={() => setType("TOUR")}
                className="h-4 w-4 text-primary focus:ring-primary"
              />
              <span>관광 (TOUR)</span>
            </label>
          </div>
        </div>

        <div className="space-y-6">
          {receiptEntries.map((entry) => (
            <ReceiptCard
              key={entry.id}
              entry={entry}
              type={type}
              onImageSelect={onImageSelect}
              onMetadataChange={onMetadataChange}
              onRemove={removeEntry}
              disabled={submitting}
            />
          ))}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={addEntry}
            disabled={submitting}
            className="min-h-[48px] rounded-xl border border-slate-200 bg-white px-4 py-2 text-slate-600 shadow-sm hover:bg-slate-50 disabled:opacity-50"
          >
            + 영수증 추가
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting}
            className="min-h-[48px] rounded-xl bg-primary px-6 py-2 font-medium text-white shadow-sm hover:bg-primary-600 focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50"
          >
            {submitting ? "제출 중…" : "제출하기"}
          </button>
        </div>

        {submitResult && submitResult.length > 0 && (
          <div className="mt-8 rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-medium text-slate-600">제출 결과</h2>
            <ul className="mt-2 space-y-2 text-sm">
              {submitResult.map((r, i) => (
                <li key={r.receiptId} className="flex flex-wrap gap-2">
                  <span className="text-slate-500">
                    #{i + 1} {r.receiptId.slice(0, 8)}…
                  </span>
                  <span
                    className={
                      r.status === "FIT"
                        ? "text-green-600"
                        : r.failReason
                        ? "text-red-600"
                        : "text-slate-600"
                    }
                  >
                    {r.status === "FIT"
                      ? "적합"
                      : r.failReason ?? r.status ?? "처리 중"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

async function pollStatus(
  receiptId: string,
  maxAttempts = 20,
  intervalMs = 1500
) {
  for (let i = 0; i < maxAttempts; i++) {
    const res = await getStatus(receiptId);
    if (
      res.status === "FIT" ||
      res.status === "UNFIT" ||
      res.status === "DUPLICATE" ||
      res.status === "ERROR"
    ) {
      return res;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { status: null, failReason: "시간 초과", amount: null, rewardAmount: 0, address: null, cardPrefix: null };
}
