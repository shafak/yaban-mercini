<?php
require_once 'auth.php';

if (isLoggedIn()) {
    header("Location: index.php");
    exit;
}

$error = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $user = $_POST['username'] ?? '';
    $pass = $_POST['password'] ?? '';

    $correct_user = getenv('ADMIN_USER') ?: 'admin';
    $correct_pass = getenv('ADMIN_PASS') ?: 'admin_pass_123';

    if ($user === $correct_user && $pass === $correct_pass) {
        $_SESSION['admin_logged_in'] = true;
        header("Location: index.php");
        exit;
    } else {
        $error = 'Geçersiz kullanıcı adı veya şifre!';
    }
}
?>
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Giriş | Yaban Mercini Admin</title>
    <link rel="stylesheet" href="style.css">
    <style>
        body { display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .login-box { background: var(--card); padding: 3rem; border-radius: 20px; border: 1px solid var(--border); width: 400px; text-align: center; }
        input { width: 100%; padding: 1rem; margin-bottom: 1rem; background: var(--bg); border: 1px solid var(--border); color: #fff; border-radius: 8px; }
        button { width: 100%; padding: 1rem; background: var(--accent); color: #000; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
        .error { color: #ff6b6b; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1 style="font-size: 1.5rem;">Yaban Mercini <span>Admin</span></h1>
        <?php if ($error): ?><div class="error"><?php echo $error; ?></div><?php endif; ?>
        <form method="POST">
            <input type="text" name="username" placeholder="Kullanıcı Adı" required>
            <input type="password" name="password" placeholder="Şifre" required>
            <button type="submit">Giriş Yap</button>
        </form>
    </div>
</body>
</html>
