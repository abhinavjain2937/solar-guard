let createMode=false;
const form=document.querySelector('#authForm');
const notice=document.querySelector('#authNotice');
function renderMode(){
  document.querySelector('#authTitle').textContent=createMode?'Create your account':'Welcome back';
  document.querySelector('#authHint').textContent=createMode?'Create a local account to keep your sites in a private workspace.':'Sign in to continue to your solar dashboard.';
  document.querySelector('#authSubmit').textContent=createMode?'Create account':'Sign in';
  document.querySelector('#switchPrompt').textContent=createMode?'Already have an account?':'New to SolarSurd?';
  document.querySelector('#switchMode').textContent=createMode?'Sign in':'Create an account';
  const password=document.querySelector('#password');
  password.autocomplete=createMode?'new-password':'current-password';
  password.minLength=createMode?12:1;
  password.placeholder=createMode?'At least 12 characters':'Enter your password';
}
document.querySelector('#switchMode').onclick=()=>{createMode=!createMode;notice.textContent='';renderMode()};
form.onsubmit=async event=>{
  event.preventDefault();notice.className='auth-notice';notice.textContent=createMode?'Creating your local account…':'Signing in…';
  const payload={email:document.querySelector('#email').value,password:document.querySelector('#password').value};
  try{
    const response=await fetch(`/api/v1/auth/${createMode?'register':'login'}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.detail||`Request failed (${response.status})`);
    notice.classList.add('success');notice.textContent='Signed in. Opening your workspace…';
    location.replace('/');
  }catch(error){notice.classList.add('error');notice.textContent=error.message}
};
renderMode();
