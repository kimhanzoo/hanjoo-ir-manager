"""Fusion matcher for remote identification.

Combines protected Protocol Core results with saved and online IR profiles.
The matcher is intentionally conservative: low-confidence or ambiguous matches
are never auto-recommended.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_FREQUENCY = 38000


def _norm(values: Iterable[Any]) -> list[int]:
    out=[]
    for idx,v in enumerate(values):
        try: n=abs(int(v))
        except (TypeError,ValueError): return []
        if n<=0: continue
        out.append(n if idx%2==0 else -n)
    return out


def raw_match(received:list[int], stored:list[int], tolerance:float=.28)->bool:
    r=_norm(received); s=_norm(stored)
    if not r or not s: return False
    if r[-1]<0: r=r[:-1]
    if s[-1]<0: s=s[:-1]
    if len(r)!=len(s) or len(r)<4: return False
    for a0,e0 in zip(r,s):
        if (a0>0)!=(e0>0): return False
        a,e=abs(a0),abs(e0)
        if abs(a-e)>max(150,int(e*tolerance)): return False
    return True


def _iter_codes(item:dict[str,Any]):
    for code in item.get('codes') or []:
        if isinstance(code,dict) and code.get('format')=='raw' and isinstance(code.get('timings'),list):
            yield code


def _signals(profile:dict[str,Any])->list[dict[str,Any]]:
    out=[]; climate=profile.get('climate') or {}
    for key in ('off','on'):
        item=climate.get(key)
        if isinstance(item,dict):
            sem={'power':key=='on'}
            if key=='off': sem['mode']='off'
            for code in _iter_codes(item): out.append({'label':key,'semantic':sem,'code':code})
    for i,cell in enumerate(climate.get('cells') or []):
        if not isinstance(cell,dict): continue
        sem={'power':True,'mode':cell.get('mode'),'temp':cell.get('temp'),'fan':cell.get('fan'),'swing':cell.get('swing')}
        for code in _iter_codes(cell): out.append({'label':f'state:{i}','semantic':sem,'code':code})
    for cid,item in (profile.get('commands') or {}).items():
        if not isinstance(item,dict): continue
        for code in _iter_codes(item): out.append({'label':str(cid),'semantic':{'command':str(cid)},'code':code})
    return out


def _sem(expected:dict[str,Any], actual:dict[str,Any])->float:
    keys=[k for k,v in expected.items() if v is not None and k in {'power','mode','temp','fan','swing','command'}]
    if not keys: return 1.0
    good=0
    for k in keys:
        a,e=actual.get(k),expected.get(k)
        if k=='temp':
            try: good += abs(float(a)-float(e))<=.51
            except (TypeError,ValueError): pass
        elif str(a).lower()==str(e).lower(): good+=1
    return good/len(keys)

@dataclass
class ProfileScore:
    matched:int; total:int; semantic_ratio:float; distinct_matches:int; confidence:int; matched_labels:list[str]


def score_profile(profile:dict[str,Any], captures:list[dict[str,Any]])->ProfileScore:
    sigs=_signals(profile); total=len(captures)
    if not sigs or not total: return ProfileScore(0,total,0,0,0,[])
    matched=0; semsum=0.; labels=[]
    for cap in captures:
        best=None; bestsem=-1.; freq=int(cap.get('frequency') or DEFAULT_FREQUENCY)
        for sig in sigs:
            code=sig['code']; cf=int(code.get('frequency') or DEFAULT_FREQUENCY)
            if abs(freq-cf)>6000: continue
            if not raw_match(cap.get('timings') or [], code.get('timings') or []): continue
            s=_sem(dict(cap.get('expected') or {}),sig['semantic'])
            if s>bestsem: best,bestsem=sig,s
        if best is not None:
            matched+=1; semsum+=max(0.,bestsem); labels.append(str(best['label']))
    mr=matched/total if total else 0; sr=semsum/matched if matched else 0; distinct=len(set(labels))
    conf=round(70*mr+25*sr+5*min(1.,distinct/max(1,min(total,3))))
    return ProfileScore(matched,total,sr,distinct,max(0,min(100,conf)),labels)


def profile_candidate(profile:dict[str,Any], captures:list[dict[str,Any]], *, source:str, candidate_id:str, catalog_id:str|None=None):
    s=score_profile(profile,captures)
    if s.matched==0: return None
    kind=str(profile.get('kind') or '')
    typ=str(profile.get('type') or '')
    if not kind: kind={'climate':'air_conditioner','fan':'fan','media_player':'tv'}.get(typ,typ or 'custom')
    return {'candidate':{'id':candidate_id,'brand':profile.get('brand'),'model':profile.get('model') or profile.get('name'),'kind':kind,'semantic_type':typ,'source':source,'profile_id':profile.get('id') if source=='saved_profile' else None,'catalog_id':catalog_id},'confidence':s.confidence,'matched_captures':s.matched,'capture_count':s.total,'semantic_ratio':round(s.semantic_ratio,4),'distinct_matches':s.distinct_matches,'matched_labels':s.matched_labels,'evidence_sources':[source],'evidence':'raw_profile_match'}


def merge_candidates(candidates:list[dict[str,Any]])->list[dict[str,Any]]:
    d={}
    for row in candidates:
        cid=str((row.get('candidate') or {}).get('id') or '')
        if cid: d[cid]=row
    rows=list(d.values())
    rows.sort(key=lambda x:(-int(x.get('confidence') or 0),-int(x.get('matched_captures') or 0),str((x.get('candidate') or {}).get('brand') or '').lower()))
    return rows


def apply_safe_recommendation(candidates:list[dict[str,Any]], capture_count:int)->dict[str,Any]:
    """Recommend only when one *protocol/profile group* is safely ahead.

    Several catalog rows can be aliases/models backed by exactly the same
    protocol family. Those rows must corroborate each other instead of being
    treated as competing guesses. Real different protocol groups still need an
    >=8 point margin.
    """
    rows=merge_candidates(candidates)
    if not rows:
        return {
            'recommended':False,
            'recommended_id':None,
            'candidates':[],
            'message_vi':'Không tìm thấy protocol/profile đủ bằng chứng từ các nguồn đang bật.',
            'message_en':'No protocol/profile has enough evidence from the enabled sources.',
            'reason_codes':['no_candidate'],
        }

    groups:dict[str,list[dict[str,Any]]]={}
    for row in rows:
        c=row.get('candidate') or {}
        gid=str(row.get('group_id') or c.get('id') or '')
        groups.setdefault(gid,[]).append(row)

    ranked_groups=[]
    for gid,members in groups.items():
        members.sort(key=lambda r:(-int(r.get('confidence') or 0),-int(r.get('matched_captures') or 0)))
        representative=members[0]
        conf=max(int(r.get('confidence') or 0) for r in members)
        matched=max(int(r.get('matched_captures') or 0) for r in members)
        sem=max(float(r.get('semantic_ratio') or 0) for r in members)
        distinct=max(int(r.get('distinct_matches') or 0) for r in members)
        core_safe=any(bool(r.get('_core_recommended')) for r in members)
        profile_safe=any(
            r.get('evidence')=='raw_profile_match'
            and capture_count>=3
            and int(r.get('matched_captures') or 0)>=3
            and int(r.get('confidence') or 0)>=92
            and float(r.get('semantic_ratio') or 0)>=.90
            and int(r.get('distinct_matches') or 0)>=2
            for r in members
        )
        ranked_groups.append({
            'group_id':gid,
            'members':members,
            'representative':representative,
            'confidence':conf,
            'matched':matched,
            'semantic_ratio':sem,
            'distinct':distinct,
            'safe':bool(core_safe or profile_safe),
        })

    ranked_groups.sort(key=lambda g:(-g['confidence'],-g['matched'],-g['semantic_ratio']))
    topg=ranked_groups[0]
    secondg=ranked_groups[1] if len(ranked_groups)>1 else None
    margin=topg['confidence']-(secondg['confidence'] if secondg else 0)
    safe=capture_count>=3 and topg['safe'] and (secondg is None or margin>=8)

    # Put all rows of the winning group first so aliases appear together.
    winning_id=topg['group_id']
    rows.sort(key=lambda r:(
        0 if str(r.get('group_id') or (r.get('candidate') or {}).get('id') or '')==winning_id else 1,
        -int(r.get('confidence') or 0),
        -int(r.get('matched_captures') or 0),
    ))

    if safe:
        c=topg['representative'].get('candidate') or {}
        return {
            'recommended':True,
            'recommended_id':c.get('id'),
            'recommended_group_id':winning_id,
            'equivalent_candidate_ids':[
                (r.get('candidate') or {}).get('id') for r in topg['members']
                if (r.get('candidate') or {}).get('id')
            ],
            'candidates':rows,
            'message_vi':'Có một protocol/profile vượt ngưỡng an toàn. Các model/alias dùng cùng protocol được xem là cùng một nhóm, không phải các đối thủ khác nhau.',
            'message_en':'One protocol/profile group passes the safety threshold. Models/aliases backed by the same protocol are treated as one group, not as competing guesses.',
            'reason_codes':[],
            'group_margin':margin if secondg else 100,
        }

    reasons=[]
    if capture_count<3: reasons.append('not_enough_samples')
    if topg['confidence']<88: reasons.append('low_confidence')
    if not topg['safe']: reasons.append('top_group_not_individually_safe')
    if secondg is not None and margin<8: reasons.append('ambiguous_protocol_groups')

    vi_map={
        'not_enough_samples':'cần ít nhất 3 mẫu',
        'low_confidence':'độ tin cậy còn thấp',
        'top_group_not_individually_safe':'nhóm đứng đầu chưa vượt kiểm tra an toàn',
        'ambiguous_protocol_groups':'các protocol khác nhau còn quá sát nhau',
    }
    en_map={
        'not_enough_samples':'at least 3 samples are required',
        'low_confidence':'confidence is still too low',
        'top_group_not_individually_safe':'the leading group has not passed the safety checks',
        'ambiguous_protocol_groups':'different protocol groups are still too close',
    }
    if not reasons: reasons=['top_group_not_individually_safe']
    return {
        'recommended':False,
        'recommended_id':None,
        'recommended_group_id':None,
        'equivalent_candidate_ids':[],
        'candidates':rows,
        'message_vi':'Không khuyến nghị tự động: '+', '.join(vi_map[r] for r in reasons)+'.',
        'message_en':'No automatic recommendation: '+', '.join(en_map[r] for r in reasons)+'.',
        'reason_codes':reasons,
        'group_margin':margin if secondg else 100,
    }

