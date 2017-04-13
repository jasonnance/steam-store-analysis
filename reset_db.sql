DROP TABLE IF EXISTS game;

CREATE TABLE game (
    steam_app_id int NOT NULL,
    game_name text,

    CONSTRAINT game_pk PRIMARY KEY (steam_app_id)
);
