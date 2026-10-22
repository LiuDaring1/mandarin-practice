// Run inside `ego-browser nodejs`, using the existing news TaskSpace.
// Source discovery and article reads all go through the actual browser page.
const fs = await import('node:fs/promises');
const root = '/Volumes/语苗计划/桌面整理2026-10-01/01_语音项目/普通话语音系统/普通话语音系统-zcode';
const dir = root + '/data/raw/news-wechat-v1';
const task = await taskSpace(24);
const page = task.page('p2');
const album = JSON.parse(await fs.readFile(dir + '/album.json', 'utf8'));
const limit = Math.min(670,album.length);
let saved = 0, failures = 0;
for (const article of album.slice(0, limit)) {
  const u = new URL(article.url);
  if(u.protocol!=='https:'||u.hostname!=='mp.weixin.qq.com'||u.pathname!=='/s'||!/^\d{8,12}$/.test(u.searchParams.get('mid')||'')||!/^\d{1,2}$/.test(u.searchParams.get('idx')||''))throw new Error('unexpected article link');
  const id = `${u.searchParams.get('mid')}-${u.searchParams.get('idx')}`;
  try {
    try { const previous = JSON.parse(await fs.readFile(`${dir}/${id}.json`, 'utf8'));
      if (previous.audio_files?.length) { saved++; continue; }
    } catch {}
    await page.goto(article.url, {timeout:15000,waitUntil:'domcontentloaded'});
    await page.waitForSelector('#js_content', {timeout:10000});
    const content = await page.evaluate(() => ({
      actual_url:location.href,
      title:document.querySelector('#activity-name')?.innerText.trim() || document.title,
      published:document.querySelector('#publish_time')?.innerText.trim(),
      text:document.querySelector('#js_content').innerText,
      audio:Array.from(document.querySelectorAll('mp-common-mpaudio,mpvoice')).map(e=>({
        id:e.getAttribute('voice_encode_fileid')||e.getAttribute('voice_encode_fileid'),
        name:e.getAttribute('name'),duration_ms:Number(e.getAttribute('play_length')),
      })).filter(a=>a.id),
    }));
    const actual=new URL(content.actual_url);
    if(actual.searchParams.get('mid')!==u.searchParams.get('mid')||actual.searchParams.get('idx')!==u.searchParams.get('idx'))throw new Error('article navigation identity mismatch');
    const audio_files = [];
    for (const [i,audio] of content.audio.entries()) {
      // This public media endpoint was observed from the rendered H5 player's currentSrc.
      const url = 'https://res.wx.qq.com/voice/getvoice?mediaid=' + encodeURIComponent(audio.id);
      const path = `${dir}/${id}-${i}.mp3`;
      // Audio download runs separately from discovered public URLs; page browsing stays sequential.
      audio_files.push({...audio,file:`${id}-${i}.mp3`,url});
    }
    if (!audio_files.length) throw new Error('no embedded audio');
    await fs.writeFile(`${dir}/${id}.json`,JSON.stringify({...article,...content,article_id:id,audio_files},null,2));
    saved++;
  } catch(error) {
    failures++;
    await fs.appendFile(dir+'/collection-errors.jsonl',JSON.stringify({article_id:id,message:String(error).slice(0,180)})+'\n');
  }
  if ((saved+failures)%10===0) console.log(JSON.stringify({saved,failures,total:limit}));
}
await fs.writeFile(dir+"/collection-complete.json",JSON.stringify({saved,failures}));
console.log(JSON.stringify({complete:true,saved,failures,total:limit}));
