import type { ReceiptEntry, ReceiptMetadata } from "../types";
import { clsx } from "clsx";

interface ReceiptCardProps {
  entry: ReceiptEntry;
  type: "STAY" | "TOUR";
  onImageSelect: (id: string, file: File) => void;
  onMetadataChange: (id: string, metadata: Partial<ReceiptMetadata>) => void;
  onRemove: (id: string) => void;
  disabled?: boolean;
}

const emptyMeta: ReceiptMetadata = {
  payDate: "",
  amount: 0,
  cardPrefix: "",
};

export function ReceiptCard({
  entry,
  type,
  onImageSelect,
  onMetadataChange,
  onRemove,
  disabled,
}: ReceiptCardProps) {
  const meta = { ...emptyMeta, ...entry.metadata };
  const isComplete = entry.status === "COMPLETE";
  const isError = entry.status === "ERROR";

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onImageSelect(entry.id, file);
  };

  return (
    <div
      className={clsx(
        "rounded-xl border bg-white p-4 shadow-sm transition",
        isError && "border-red-200",
        !isError && "border-slate-100"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-600">영수증 #{entry.id.slice(0, 8)}</h3>
        <button
          type="button"
          onClick={() => onRemove(entry.id)}
          disabled={disabled}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600 disabled:opacity-50"
          aria-label="삭제"
        >
          <TrashIcon />
        </button>
      </div>

      {/* 이미지 영역 */}
      <div className="mt-3">
        <label className="block text-sm text-slate-500">영수증 이미지</label>
        <div className="mt-1 flex min-h-[120px] items-center justify-center rounded-lg border-2 border-dashed border-slate-200 bg-slate-50">
          {entry.previewUrl ? (
            <img
              src={entry.previewUrl}
              alt="영수증 미리보기"
              className="max-h-40 rounded object-contain"
            />
          ) : (
            <span className="text-slate-400">이미지를 선택하세요</span>
          )}
        </div>
        <input
          type="file"
          accept="image/jpeg,image/png,image/jpg"
          onChange={handleFile}
          disabled={disabled || entry.status === "UPLOADING"}
          className="mt-2 block w-full text-sm text-slate-600 file:mr-2 file:rounded-lg file:border-0 file:bg-primary file:px-4 file:py-2 file:text-white"
          aria-label="영수증 이미지 선택"
        />
        {entry.status === "UPLOADING" && (
          <p className="mt-1 text-sm text-primary">업로드 중...</p>
        )}
        {entry.status === "COMPLETE" && (
          <p className="mt-1 text-sm text-green-600">업로드 완료</p>
        )}
        {entry.errorMessage && (
          <p className="mt-1 text-sm text-red-600">{entry.errorMessage}</p>
        )}
      </div>

      {/* 폼: 타입별 필수 필드 */}
      <div className="mt-4 space-y-3">
        {type === "STAY" && (
          <div>
            <label className="block text-sm text-slate-600">소재지(시군) *</label>
            <input
              type="text"
              value={meta.location ?? ""}
              onChange={(e) =>
                onMetadataChange(entry.id, { location: e.target.value })
              }
              placeholder="예: 춘천시"
              disabled={disabled}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-base focus:ring-2 focus:ring-primary focus:ring-offset-0"
            />
          </div>
        )}
        {type === "TOUR" && (
          <div>
            <label className="block text-sm text-slate-600">상호명 *</label>
            <input
              type="text"
              value={meta.storeName ?? ""}
              onChange={(e) =>
                onMetadataChange(entry.id, { storeName: e.target.value })
              }
              placeholder="예: 강원맛식당"
              disabled={disabled}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-base focus:ring-2 focus:ring-primary focus:ring-offset-0"
            />
          </div>
        )}
        <div>
          <label className="block text-sm text-slate-600">결제일 *</label>
          <input
            type="text"
            value={meta.payDate}
            onChange={(e) =>
              onMetadataChange(entry.id, { payDate: e.target.value })
            }
            placeholder="2026-05-20"
            disabled={disabled}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-base focus:ring-2 focus:ring-primary focus:ring-offset-0"
          />
        </div>
        <div>
          <label className="block text-sm text-slate-600">결제금액(원) *</label>
          <input
            type="number"
            min={0}
            value={meta.amount || ""}
            onChange={(e) =>
              onMetadataChange(entry.id, {
                amount: parseInt(e.target.value, 10) || 0,
              })
            }
            placeholder="50000"
            disabled={disabled}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-base focus:ring-2 focus:ring-primary focus:ring-offset-0"
          />
        </div>
        <div>
          <label className="block text-sm text-slate-600">카드 앞 4자리 *</label>
          <input
            type="text"
            inputMode="numeric"
            maxLength={4}
            value={meta.cardPrefix}
            onChange={(e) =>
              onMetadataChange(entry.id, {
                cardPrefix: e.target.value.replace(/\D/g, "").slice(0, 4),
              })
            }
            placeholder="1234"
            disabled={disabled}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-base focus:ring-2 focus:ring-primary focus:ring-offset-0"
          />
        </div>
      </div>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
      />
    </svg>
  );
}
