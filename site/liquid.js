/* The mark as liquid metal: one WebGL canvas on the landing page, nothing loaded from anywhere. The mark's own SVG,
   already on the page, is drawn to a small canvas for a mask; the shader turns the mask into a height field,
   wobbles it slowly with noise, and shades it as polished metal under a studio-like light, in the band's violet.
   Without WebGL, or when the visitor asked for less motion, the page keeps the still mark; nothing waits on it. */
(function () {
  var visual = document.querySelector(".visual");
  var canvas = visual && visual.querySelector("canvas.liquid");
  var still = visual && visual.querySelector("svg");
  if (!canvas || !still) { return; }
  var motion = matchMedia("(prefers-reduced-motion: no-preference)").matches;
  var gl = canvas.getContext("webgl2", { alpha: true, antialias: false, premultipliedAlpha: true });
  if (!gl) { return; }

  var VERT = "#version 300 es\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0.,1.);}";
  var FRAG = [
    "#version 300 es",
    "precision highp float;",
    "uniform sampler2D u_mask; uniform float u_time; uniform vec2 u_res; out vec4 o;",
    "float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}",
    "float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);float a=hash(i),b=hash(i+vec2(1,0)),c=hash(i+vec2(0,1)),d=hash(i+vec2(1,1));return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);}",
    "float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<4;i++){v+=a*noise(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return v;}",
    "float height(vec2 uv){float m=textureLod(u_mask,uv,1.9).a;float m2=textureLod(u_mask,uv,3.4).a;return smoothstep(.08,.92,m)*.7+m2*.3;}",
    "void main(){",
    "  vec2 uv=gl_FragCoord.xy/u_res; uv.y=1.-uv.y; float t=u_time;",
    "  vec2 w=(vec2(fbm(uv*2.6+t*.11),fbm(uv*2.6-t*.09+5.))-.5)*.03;",
    "  vec2 p=uv+w;",
    "  float a=smoothstep(.42,.58,textureLod(u_mask,p,1.0).a);",
    "  if(a<.003){o=vec4(0.);return;}",
    "  float e=1.6/u_res.x;",
    "  float hx=height(p+vec2(e,0.))-height(p-vec2(e,0.));",
    "  float hy=height(p+vec2(0.,e))-height(p-vec2(0.,e));",
    "  float r1=fbm(p*7.+vec2(t*.25,-t*.18))-.5, r2=fbm(p*7.+3.1-t*.21)-.5;",
    "  vec3 n=normalize(vec3(-hx*9.+r1*.38,-hy*9.+r2*.38,1.));",
    "  vec3 v=vec3(0.,0.,1.); vec3 rf=reflect(-v,n);",
    "  float y=rf.y; float env=.4+smoothstep(0.,.6,y)*.6-smoothstep(0.,-.7,y)*.3;",
    "  env+=exp(-pow(y*14.,2.))*.5;",
    "  env+=exp(-pow((rf.x+.6)*4.,2.))*.15;",
    "  vec3 silver=vec3(.9,.91,.97), shade=vec3(.15,.11,.34);",
    "  vec3 c=mix(shade,silver,clamp(env,0.,1.));",
    "  vec3 l=normalize(vec3(-.45,.8,.55));",
    "  c+=pow(max(dot(reflect(-l,n),v),0.),90.)*1.;",
    "  c+=pow(1.-max(dot(n,v),0.),3.)*vec3(.75,.7,1.)*.35;",
    "  o=vec4(c*a,a);",
    "}"
  ].join("\n");

  function shader(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  }
  var vs = shader(gl.VERTEX_SHADER, VERT), fs = shader(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) { return; }
  var program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { return; }
  gl.useProgram(program);
  var uTime = gl.getUniformLocation(program, "u_time"), uRes = gl.getUniformLocation(program, "u_res");

  // The mask: the still mark, drawn white on nothing into a square with room around it for the blur.
  var SIZE = 512;
  var mask = document.createElement("canvas");
  mask.width = mask.height = SIZE;
  var ctx = mask.getContext("2d");
  var copy = still.cloneNode(true);
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("fill", "#fff");
  copy.removeAttribute("class");
  var url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml" }));
  var img = new Image();
  img.onload = function () {
    URL.revokeObjectURL(url);
    var inset = SIZE * 0.2, side = SIZE - inset * 2;
    ctx.clearRect(0, 0, SIZE, SIZE);
    ctx.drawImage(img, inset, inset, side, side);
    var tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, mask);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    start();
  };
  img.onerror = function () { URL.revokeObjectURL(url); };
  img.src = url;

  function fit() {
    var dpr = Math.min(devicePixelRatio || 1, 2);
    var w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
    gl.uniform2f(uRes, w, h);
  }
  function frame(t) {
    fit();
    gl.uniform1f(uTime, t);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  var seen = true, began = 0, raf = 0;
  function loop(now) {
    raf = 0;
    if (!seen) { return; }
    frame((now - began) / 1000);
    raf = requestAnimationFrame(loop);
  }
  function start() {
    visual.classList.add("live");
    frame(0);
    if (!motion) { return; }
    began = performance.now();
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        seen = entries[0].isIntersecting;
        if (seen && !raf) { raf = requestAnimationFrame(loop); }
      }).observe(canvas);
    } else {
      raf = requestAnimationFrame(loop);
    }
    addEventListener("resize", function () { if (!raf) { frame((performance.now() - began) / 1000); } });
  }
})();
