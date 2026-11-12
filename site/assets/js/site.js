/* NodeWatch · site de apresentação. Sem dependências, sem rastreamento. */
(function () {
  "use strict";

  /* ---------- Menu compacto no celular ---------- */
  var botaoMenu = document.querySelector(".menu-botao");
  var menu = document.getElementById("menu-principal");

  function fecharMenu() {
    menu.classList.remove("aberto");
    botaoMenu.setAttribute("aria-expanded", "false");
  }

  if (botaoMenu && menu) {
    botaoMenu.addEventListener("click", function () {
      var aberto = menu.classList.toggle("aberto");
      botaoMenu.setAttribute("aria-expanded", aberto ? "true" : "false");
    });
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) fecharMenu();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menu.classList.contains("aberto")) {
        fecharMenu();
        botaoMenu.focus();
      }
    });
    document.addEventListener("click", function (e) {
      if (menu.classList.contains("aberto") && !e.target.closest(".cabecalho")) fecharMenu();
    });
  }

  /* ---------- Capturas: aviso de pendência e ampliação ---------- */
  var lightbox = document.querySelector(".lightbox");
  var lbImg = lightbox && lightbox.querySelector(".lightbox-img");
  var lbLegenda = lightbox && lightbox.querySelector(".lightbox-legenda");
  var lbFechar = lightbox && lightbox.querySelector(".lightbox-fechar");
  var origemFoco = null;

  function marcarFaltando(figura, botao) {
    figura.classList.add("faltando");
    botao.setAttribute("aria-disabled", "true");
    botao.setAttribute("tabindex", "-1");
    botao.setAttribute("aria-label", "Captura " + figura.dataset.id + " pendente");
  }

  function abrir(img, legenda) {
    if (!lightbox || typeof lightbox.showModal !== "function") {
      window.open(img.currentSrc || img.src, "_blank", "noopener");
      return;
    }
    origemFoco = document.activeElement;
    lbImg.src = img.currentSrc || img.src;
    lbImg.alt = img.alt;
    lbLegenda.innerHTML = legenda.innerHTML;
    lightbox.showModal();
    lbFechar.focus();
  }

  if (lightbox) {
    lbFechar.addEventListener("click", function () { lightbox.close(); });
    // Clique fora da imagem (no fundo escurecido) também fecha.
    lightbox.addEventListener("click", function (e) {
      if (e.target === lightbox) lightbox.close();
    });
    lightbox.addEventListener("close", function () {
      lbImg.removeAttribute("src");
      if (origemFoco) origemFoco.focus();
    });
  }

  document.querySelectorAll(".tela").forEach(function (figura) {
    var botao = figura.querySelector(".tela-abrir");
    var img = figura.querySelector("img");
    var legenda = figura.querySelector("figcaption");

    img.addEventListener("error", function () { marcarFaltando(figura, botao); });
    if (img.complete && img.naturalWidth === 0 && img.getAttribute("src")) marcarFaltando(figura, botao);

    botao.addEventListener("click", function () {
      if (figura.classList.contains("faltando")) return;
      abrir(img, legenda);
    });
  });

  /* ---------- Vídeo: só carrega ao toque, sem autoplay ---------- */
  var player = document.querySelector(".player");
  if (player) {
    var url = (player.dataset.video || "").trim();
    var legenda = (player.dataset.legenda || "").trim();
    var pendente = !url || url.charAt(0) === "[";
    var play = player.querySelector(".player-play");
    var aviso = player.querySelector(".player-aviso");
    var capa = player.querySelector(".player-capa");

    if (!pendente) {
      aviso.hidden = true;
      play.hidden = false;
      play.addEventListener("click", function () { carregarVideo(); });
    }

    function idYouTube(u) {
      var m = u.match(/(?:youtu\.be\/|youtube(?:-nocookie)?\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/))([\w-]{11})/);
      return m ? m[1] : null;
    }

    function carregarVideo() {
      var yt = idYouTube(url);
      var el;
      if (yt) {
        el = document.createElement("iframe");
        el.src = "https://www.youtube-nocookie.com/embed/" + yt +
          "?autoplay=1&rel=0&cc_load_policy=1&cc_lang_pref=pt&hl=pt-BR";
        el.title = "Vídeo pitch do NodeWatch";
        el.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
        el.allowFullscreen = true;
      } else if (/\.(mp4|webm)(\?|#|$)/i.test(url)) {
        el = document.createElement("video");
        el.controls = true;
        el.playsInline = true;
        el.preload = "metadata";
        if (capa) el.poster = capa.currentSrc || capa.src;
        el.src = url;
        if (legenda) {
          var trilha = document.createElement("track");
          trilha.kind = "captions";
          trilha.srclang = "pt-BR";
          trilha.label = "Português";
          trilha.src = legenda;
          trilha.default = true;
          el.appendChild(trilha);
        }
        el.setAttribute("aria-label", "Vídeo pitch do NodeWatch");
      } else {
        window.open(url, "_blank", "noopener");
        return;
      }
      player.replaceChildren(el);
      if (el.tagName === "VIDEO") {
        // Começa porque a pessoa tocou no botão; nunca sozinho.
        var p = el.play();
        if (p && p.catch) p.catch(function () {});
        el.focus();
      }
    }
  }

  /* ---------- Cabeçalho: link da seção visível ---------- */
  var links = Array.prototype.slice.call(document.querySelectorAll('.menu a[href^="#"]'));
  if (links.length && "IntersectionObserver" in window) {
    var porId = {};
    links.forEach(function (a) { porId[a.getAttribute("href").slice(1)] = a; });
    var marcar = function (id) {
      links.forEach(function (a) { a.removeAttribute("aria-current"); });
      if (porId[id]) porId[id].setAttribute("aria-current", "location");
    };
    // Faixa no meio da tela: a seção que a cruza é a seção atual.
    var observador = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (e) { if (e.isIntersecting) marcar(e.target.id); });
    }, { rootMargin: "-45% 0px -50% 0px" });
    document.querySelectorAll("main > section[id]").forEach(function (s) { observador.observe(s); });
  }

  /* ---------- Entrada suave dos blocos ---------- */
  // Só com movimento permitido. Sem JS, ou com movimento reduzido, tudo aparece de imediato.
  var semMovimento = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!semMovimento && "IntersectionObserver" in window) {
    var blocos = document.querySelectorAll(
      ".passo, .tela, .cartao, .etapas li, .situacao li, .faixa-aviso, .faq details, .opcional, .player"
    );
    var revelador = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("visivel");
          revelador.unobserve(e.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    var alturaTela = window.innerHeight || document.documentElement.clientHeight;
    blocos.forEach(function (b) {
      // O que já está na tela ao carregar não é escondido.
      if (b.getBoundingClientRect().top < alturaTela) return;
      b.classList.add("revelar");
      revelador.observe(b);
    });
  }
})();
