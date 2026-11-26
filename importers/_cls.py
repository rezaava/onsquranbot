import re
HAR=re.compile(r'[\u064B-\u0652\u0670]')
FA_W=set("و در به از که را این با است بود شد می مى كه براى برای تا آن یا يا هم نیز اى ای مرا ما تو او ما خدا خداوندا پروردگارا بر هر همه های ها ام ات اش بگو بخوان".split())
AR_W=set("من على في فى الى إلى ما لا إن ان أن الذي الّذي اللهم اللّهم يا عن إنك انك وَ بِسْمِ".split())
def norm(s): return HAR.sub('',s).replace('\xa0',' ').replace('ي','ی').replace('ك','ک')
def kind(s):
    n=norm(s); ws=re.findall(r'[\u0600-\u06FF]+',n)
    if not ws: return None
    h=len(HAR.findall(s))/max(1,len(n.replace(' ','')))
    fa=sum(w in FA_W or w.endswith(('ها','های','ان','ام')) for w in ws)/len(ws)
    pers=len(re.findall('[پچگژ]',n))
    mi=len(re.findall(r'\bمی\b|\bمى\b|\bمی ',s))
    sc=(-3 if h>0.25 else 0)+fa*4+(pers>0)*1+(mi>0)*2 - sum(w in AR_W for w in ws)/len(ws)*3 + (-2 if re.search(r'\bال\w+',n) and fa<0.15 else 0)
    return 'fa' if sc>0.4 else 'ar'
