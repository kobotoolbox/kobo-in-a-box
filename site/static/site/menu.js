// The menu on narrow screens, where the header's links and the sidebar are hidden. It's
// built from links the page already has: the sidebar ("On this page") and the footer's
// "In detail" guides, with the overview first on the guide pages.
(function () {
  var header = document.querySelector('.header .wrap');
  if (!header) return;

  var panel = document.createElement('nav');
  panel.className = 'menu';
  panel.id = 'menu';
  panel.setAttribute('aria-label', 'Menu');
  panel.hidden = true;

  function group(label, links) {
    if (!links.length) return;
    var title = document.createElement('span');
    title.className = 'menu__label';
    title.textContent = label;
    var ul = document.createElement('ul');
    links.forEach(function (a) {
      var li = document.createElement('li');
      var copy = document.createElement('a');
      copy.href = a.getAttribute('href');
      copy.textContent = a.textContent;
      li.appendChild(copy);
      ul.appendChild(li);
    });
    panel.appendChild(title);
    panel.appendChild(ul);
  }

  var home = !!document.querySelector('.header__nav a[href^="#"]');
  if (!home) {
    var overview = document.createElement('a');
    overview.setAttribute('href', './');
    overview.textContent = 'Overview';
    group('Kobo in a box', [overview]);
  }
  group('On this page', [].slice.call(document.querySelectorAll('.docs__nav a')));
  var guides = [].filter.call(document.querySelectorAll('.footer__label'), function (l) {
    return l.textContent.trim() === 'In detail';
  })[0];
  group('In detail', guides ? [].slice.call(guides.parentNode.querySelectorAll('a')) : []);

  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'header__menu';
  button.setAttribute('aria-controls', 'menu');
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-label', 'Menu');
  button.innerHTML = '<span></span><span></span><span></span>';

  function toggle(open) {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    document.documentElement.classList.toggle('menu-open', open);
  }

  button.addEventListener('click', function () { toggle(panel.hidden); });
  panel.addEventListener('click', function (e) { if (e.target.closest('a')) toggle(false); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden) { toggle(false); button.focus(); }
  });
  matchMedia('(width > 834px)').addEventListener('change', function (m) { if (m.matches) toggle(false); });

  header.appendChild(button);
  document.querySelector('.header').appendChild(panel);
})();
