#!/bin/bash

echo "Pulizia della cache del sistema..."

# Pulizia della cache delle applicazioni
sudo rm -rfv ~/Library/Caches/*
sudo rm -rfv /Library/Caches/*

# Pulizia della cache di sistema
sudo rm -rfv /System/Library/Caches/*
sudo rm -rfv /private/var/folders/*

# Pulizia della cache dei browser (Safari, Chrome, Firefox)
sudo rm -rfv ~/Library/Safari/*
sudo rm -rfv ~/Library/Application\ Support/Google/Chrome/Default/Application\ Cache/*
sudo rm -rfv ~/Library/Application\ Support/Firefox/Profiles/*.default-release/cache2/*

echo "Pulizia completata!"
