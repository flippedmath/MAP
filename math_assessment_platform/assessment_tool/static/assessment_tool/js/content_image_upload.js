/**
 * Shared helper: upload an image file to /api/content-images/upload/ and
 * return the public media URL. Exposes window.MAPContentImages.
 */
(function (global) {
  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function uploadImageFile(file, options) {
    options = options || {};
    if (!file) {
      return Promise.reject(new Error('No file selected.'));
    }
    var form = new FormData();
    form.append('image', file, file.name || 'image');
    return fetch(options.url || '/api/content-images/upload/', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken() },
      credentials: 'same-origin',
      body: form
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || !data || !data.success || !data.url) {
          var msg = (data && data.error) || 'Image upload failed.';
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  global.MAPContentImages = {
    uploadImageFile: uploadImageFile,
    csrfToken: csrfToken
  };
})(typeof window !== 'undefined' ? window : this);
