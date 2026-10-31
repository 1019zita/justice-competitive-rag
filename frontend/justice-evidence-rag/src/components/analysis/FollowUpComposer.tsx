import { useState } from "react";

type FollowUpComposerProps = { suggestions: string[]; initialValue?: string; onValueChange?: (value: string) => void; onSubmit: (value: string) => void };

export function FollowUpComposer({ suggestions, initialValue = "", onValueChange, onSubmit }: FollowUpComposerProps) {
  const [value, setValue] = useState(initialValue);
  function update(nextValue: string) { setValue(nextValue); onValueChange?.(nextValue); }
  function submit(event: React.FormEvent<HTMLFormElement>) { event.preventDefault(); if (value.trim()) onSubmit(value.trim()); }
  return <section className="follow-up" aria-label="继续交互"><div className="follow-up-heading"><span className="section-kicker">CONTINUE REVIEW</span><h3>继续核查这个案件</h3></div><form className="composer-form" onSubmit={submit}><textarea value={value} onChange={event => update(event.target.value)} placeholder="补充案件事实，或继续询问当前分析……" rows={2} /><div className="composer-bottom"><div className="quick-actions"><button type="button" onClick={() => update("补充事实：")}>＋ 补充事实</button><button type="button" onClick={() => update("重点重新核查：")}>↻ 重新核查</button><button type="button" onClick={() => update("继续追问：")}>⌁ 继续追问</button></div><button className="send-button" type="submit" disabled={!value.trim()}>发送 <span>↑</span></button></div></form><div className="suggestion-row"><span>试试：</span>{suggestions.map(suggestion => <button type="button" key={suggestion} onClick={() => update(suggestion)}>{suggestion}</button>)}</div></section>;
}
