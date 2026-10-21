// 실제 모델로 생성·저장된 대화를 브라우저에서 불러와 캡처한다. 응답을 합성하지 않는다.
const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const data=JSON.parse(fs.readFileSync('eval/local_model_results.json','utf8'));
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'chrome'});
 const context=await browser.newContext({viewport:{width:1280,height:1000}});
 await context.addInitScript(({thread})=>{
  localStorage.setItem('incident-agent.current.v1',thread);
  localStorage.setItem('incident-agent.sessions.v1',JSON.stringify([{id:thread,title:'실제 Ollama 진단·후속 요청'}]));
 },{thread:data.thread_id});
 const page=await context.newPage();
 await page.goto('http://127.0.0.1:8600');
 await page.waitForFunction(()=>document.querySelector('.notice')?.textContent.includes('메시지 4개'));
 await page.screenshot({path:'doc/evidence/live-01-ollama-restored.png'});
 await page.locator('#log').evaluate(e=>e.scrollTop=0);
 await page.screenshot({path:'doc/evidence/live-02-ollama-first-turn.png'});
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await page.screenshot({path:'doc/evidence/live-03-mobile.png'});
 await browser.close();console.log('실제 Ollama 화면 캡처 완료');
})().catch(e=>{console.error(e);process.exit(1)});
