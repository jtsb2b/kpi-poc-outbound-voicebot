import { useEffect, useRef } from "react";
import type { TranscriptTurn } from "../api";
import { PhoneIcon } from "../icons";

export function Transcript({
  turns,
  follow = false,
  waiting = false,
}: {
  turns: TranscriptTurn[];
  follow?: boolean;
  waiting?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [turns.length, follow, waiting]);

  if (turns.length === 0 && !waiting) {
    return (
      <div className="empty">
        <PhoneIcon size={28} />
        <span>บทสนทนาจะแสดงที่นี่เมื่อผู้รับสายรับสาย</span>
      </div>
    );
  }
  return (
    <div className="transcript" ref={box} aria-live={follow ? "polite" : undefined}>
      {turns.map((t, i) => {
        const unspoken =
          t.interrupted && t.generated_text && t.generated_text.startsWith(t.text)
            ? t.generated_text.slice(t.text.length)
            : "";
        const showSpeaker = i === 0 || turns[i - 1].speaker !== t.speaker || t.interrupted;
        return (
          <div key={t.seq} style={{ display: "contents" }}>
            {showSpeaker && (
              <span className={`speaker ${t.speaker}`}>
                {t.speaker === "bot" ? "น้องเคพีไอ" : "ลูกค้า"}
                {t.interrupted && <span className="cut"> · ถูกพูดแทรก</span>}
              </span>
            )}
            <div className={`bubble ${t.speaker}`}>
              {t.text}
              {unspoken && (
                <span className="unspoken" title="ส่วนที่ยังไม่ได้พูด">
                  {unspoken}
                </span>
              )}
            </div>
          </div>
        );
      })}
      {waiting && (
        <div className="typing" aria-label="กำลังสนทนา">
          <span />
          <span />
          <span />
        </div>
      )}
    </div>
  );
}
