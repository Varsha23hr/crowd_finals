import pygame

pygame.mixer.init()

SIREN_FILE = "static/siren.mp3"

playing = False


def play_siren():
    global playing

    if not playing:
        pygame.mixer.music.load(SIREN_FILE)
        pygame.mixer.music.play(-1)
        playing = True


def stop_siren():
    global playing

    if playing:
        pygame.mixer.music.stop()
        playing = False