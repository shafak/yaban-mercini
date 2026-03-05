<?php
session_start();

function isLoggedIn() {
    return isset($_SESSION['admin_logged_in']) && $_SESSION['admin_logged_in'] === true;
}

function checkLogin() {
    if (!isLoggedIn()) {
        header("Location: login.php");
        exit;
    }
}
?>
