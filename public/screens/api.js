const API_URL = "http://127.0.0.1:8000";

async function api(endpoint, options = {}) {

    const token = localStorage.getItem("token");

    const headers = {

        ...(options.headers || {}),

        Authorization: token
            ? `Bearer ${token}`
            : ""

    };

    // Only set JSON content type if we're NOT uploading files
    if (!(options.body instanceof FormData)) {

        headers["Content-Type"] = "application/json";

    }

    const response = await fetch(
        API_URL + endpoint,
        {

            ...options,

            headers

        }
    );

    if (response.status === 401) {

        localStorage.removeItem("token");

        alert("Session expired. Please login again.");

        window.location.href = "index.html";

        return;

    }

    return response;

}