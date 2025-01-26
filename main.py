from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from typing import List, Optional
from passlib.context import CryptContext
import redis
import json


# Database Configuration
DATABASE_URL = "mysql+pymysql://root:db2025@localhost/projektup"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis Configuration
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Password Hashing Configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Models (SQLAlchemy)
class Artikal(Base):
    __tablename__ = "artikli"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255))
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    category = relationship("Category", back_populates="artikli")
    


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    #artikli = Column(String, nullable=True) 

    artikli = relationship("Artikal", back_populates="category", cascade="all, delete")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)


class Recenzija(Base):
    __tablename__ = "recenzija"
    id = Column(Integer, primary_key=True, index=True)
    rating = Column(String(50), nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    artikal_id = Column(Integer, ForeignKey("artikli.id"))
    user_id = Column(Integer, ForeignKey("users.id"))

    artikal = relationship("Artikal")
    user = relationship("User")

# Create all tables in the database
Base.metadata.create_all(bind=engine)

# Pydantic Schemas
class ArtikalCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category_id: Optional[int] = None


class ArtikalResponse(ArtikalCreate):
    id: int

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str
    
    


class CategoryResponse(CategoryCreate):
    id: int


    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    name: str
    email: str
    password: str

    


class UserResponse(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True


class RecenzijaCreate(BaseModel):
    rating: str


class RecenzijaResponse(RecenzijaCreate):
    id: int

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    artikal_id: int
    user_id: int


class OrderResponse(OrderCreate):
    id: int
    user_id: int
    artikal_id: int

    class Config:
        from_attributes = True


# FastAPI App
app = FastAPI()

# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Password Hashing
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# CRUD Routes
@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    # Provjera je li email već registriran
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered.")

    # Hashiranje lozinke i spremanje novog korisnika
    hashed_password = hash_password(user.password)
    db_user = User(name=user.name, email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)


    return db_user

@app.post("/login")
def login(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials.")
    return {"message": "Login successful"}


## Users
@app.post("/users", response_model=UserResponse, tags=["Users"])
def create_user(new_user: UserCreate, db: Session = Depends(get_db)):
    # Proveri da li korisnik sa istim emailom već postoji
    existing_user = db.query(User).filter(User.email == new_user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Kreiraj novog korisnika
    hashed_password = hash_password(new_user.password)
    db_user = User(name=new_user.name, email=new_user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Obrisi Redis keš za korisnike
    try:
        redis_client.delete("users")
    except Exception as e:
        print(f"Greška prilikom brisanja Redis keša: {e}")

    return db_user


@app.get("/users/", response_model=List[UserResponse], tags=["Users"])
def list_users(db: Session = Depends(get_db)):
    # Dohvaćanje korisnika iz Redis keša
    users = redis_client.get("users")
    if users:
        return json.loads(users)

    # Dohvaćanje korisnika iz baze
    users = db.query(User).all()
    users_list = [{"id": user.id, "name": user.name, "email": user.email} for user in users]

    # Ažuriranje Redis keša
    redis_client.set("users", json.dumps(users_list))

    return users


@app.put("/users/{user_id}", response_model=UserResponse, tags=["Users"])
def update_user(user_id: int, updated_user: UserCreate, db: Session = Depends(get_db)):
    # Provera da li korisnik postoji u bazi
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Ažuriranje podataka korisnika
    db_user.name = updated_user.name
    db_user.email = updated_user.email
    db_user.hashed_password = hash_password(updated_user.password)
    db.commit()
    db.refresh(db_user)

    # Brisanje Redis keša
    try:
        redis_client.delete("users")
    except Exception as e:
        # Ako dođe do greške u Redis-u, korisnika ipak vraćamo
        print(f"Greška prilikom brisanja Redis keša: {e}")

    return db_user

@app.delete("/users/{user_id}", tags=["Users"])
def delete_user(user_id: int, db: Session = Depends(get_db)):
    # Provjera postojanja korisnika
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Brisanje povezanih narudžbi
    db.query(Order).filter(Order.user_id == user_id).delete()
    
    # Brisanje korisnika
    db.delete(db_user)
    db.commit()

    # Uklanjanje iz cachea
    redis_client.delete(f"user:{user_id}")
    redis_client.delete("users")

    return 


## Categories
@app.post("/categories/", response_model=CategoryResponse, tags=["Users"])
def create_category(category: CategoryCreate, db: Session = Depends(get_db)):
    db_category = Category(name=category.name)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)

    # Cache the category in Redis
    redis_client.delete("categories")

    return db_category



@app.get("/categories/", response_model=List[CategoryResponse], tags=["Users"])
def list_categories(db: Session = Depends(get_db)):
    # Dohvaćanje kategorija iz Redis keša
    categories = redis_client.get("categories")
    if categories:
        return json.loads(categories)

    # Dohvaćanje kategorija iz baze
    categories = db.query(Category).all()
    categories_list = [{"id": category.id, "name": category.name} for category in categories]  # Uklonjen 'description'

    # Ažuriranje Redis keša
    redis_client.set("categories", json.dumps(categories_list))

    return categories_list


@app.put("/categories/{category_id}", response_model=CategoryResponse, tags=["Users"])
def update_category(category_id: int, updated_category: CategoryCreate, db: Session = Depends(get_db)):
    # Provjera postoji li kategorija u bazi
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Ažuriranje kategorije u bazi podataka
    db_category.name = updated_category.name
    db.commit()
    db.refresh(db_category)

    # Brisanje Redis keša
    try:
        redis_client.delete("categories")
    except Exception as e:
        # Ako dođe do greške u Redis-u, kategoriju ipak vraćamo
        print(f"Greška prilikom brisanja Redis keša: {e}")

    return db_category

@app.delete("/categories/{category_id}", tags=["Users"])
def delete_category(category_id: int, db: Session = Depends(get_db)):
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(db_category)
    db.commit()

    redis_client.delete("categories")
    redis_client.delete(f"category:{category_id}")
    return 

## Artikli
@app.post("/artikli/", response_model=ArtikalResponse, tags=["Users"])
def create_artikal(artikal: ArtikalCreate, db: Session = Depends(get_db)):
    # Provjera postojanja kategorije
    if artikal.category_id:
        category = db.query(Category).filter(Category.id == artikal.category_id).first()
        if not category:
            raise HTTPException(status_code=400, detail="Category does not exist")

    # Kreiranje artikla
    db_artikal = Artikal(name=artikal.name, description=artikal.description, category_id=artikal.category_id)
    db.add(db_artikal)
    db.commit()
    db.refresh(db_artikal)

    # Brisanje Redis keša
    redis_client.delete("artikli")

    return db_artikal

@app.get("/artikli/", response_model=List[ArtikalResponse], tags=["Users"])
def list_artikli(db: Session = Depends(get_db)):
    # Provjera Redis keša
    cached_artikli = redis_client.get("artikli")
    if cached_artikli:
        return json.loads(cached_artikli)  # Ako postoji keš, vrati podatke iz Redis-a
    

    # Ako nema keša, dohvatiti podatke iz baze
    artikli = db.query(Artikal).all()

    # Provjeri ima li podataka u bazi
    if not artikli:
        raise HTTPException(status_code=404, detail="Nema artikala u bazi.")

    # Priprema podataka za keširanje i povrat
    artikli_list = [
        {
            "id": artikal.id,
            "name": artikal.name,
            "description": artikal.description,
            "category_id": artikal.category_id,
        }
        for artikal in artikli
    ]

    # Spremi podatke u Redis keš
    redis_client.set("artikli", json.dumps(artikli_list))

    return artikli_list



@app.put("/artikli/{artikal_id}", response_model=ArtikalResponse, tags=["Users"])
def update_artikal(artikal_id: int, updated_artikal: ArtikalCreate, db: Session = Depends(get_db)):
    db_artikal = db.query(Artikal).filter(Artikal.id == artikal_id).first()
    if not db_artikal:
        raise HTTPException(status_code=404, detail="Artikal not found")

    db_artikal.name = updated_artikal.name
    db_artikal.description = updated_artikal.description
    db.commit()
    db.refresh(db_artikal)
    redis_client.delete("artikli")
    redis_client.set(f"artikal:{artikal_id}", json.dumps({"id": db_artikal.id, "name": db_artikal.name, "description": db_artikal.description, "category_id": db_artikal.category_id}))
    return db_artikal

@app.delete("/artikli/{artikal_id}", tags=["Users"])
def delete_artikal(artikal_id: int, db: Session = Depends(get_db)):
    db_artikal = db.query(Artikal).filter(Artikal.id == artikal_id).first()
    if not db_artikal:
        raise HTTPException(status_code=404, detail="Artikal not found")
    db.delete(db_artikal)
    db.commit()

    redis_client.delete("artikli")
    redis_client.delete(f"artikli:{artikal_id}")
    return

## Orders
@app.post("/orders/", response_model=OrderResponse, tags=["Users"])
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    db_order = Order(artikal_id=order.artikal_id, user_id=order.user_id)
    db.add(db_order)
    db.commit()
    db.refresh(db_order)

    # Cache the new order
    redis_client.delete("orders")
    redis_client.set(f"order:{db_order.id}", json.dumps({"id": db_order.id, "user_id": db_order.user_id}))
    return db_order


@app.get("/orders/", response_model=List[OrderResponse], tags=["Users"])
def list_orders(db: Session = Depends(get_db)):
    cached_orders = redis_client.get("orders")
    
    if cached_orders:
        # Parsiramo JSON i mapiramo u Pydantic modele
        orders = json.loads(cached_orders)
        return [OrderResponse(**order) for order in orders]

    # Dohvati podatke iz baze
    orders = db.query(Order).all()
    
    # Transformišemo podatke u ispravan JSON format
    orders_data = [{"id": order.id, "user_id": order.user_id, "artikal_id": order.artikal_id} for order in orders]

    # Keširamo podatke u Redis (dodali smo expire na 10 minuta)
    redis_client.set("orders", json.dumps(orders_data), ex=600)

    return orders
@app.put("/orders/{order_id}", response_model=OrderResponse, tags=["Users"])
def update_order(order_id: int, updated_order: OrderCreate, db: Session = Depends(get_db)):
    db_order = db.query(Order).filter(Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")

    db_order.artikal_id = updated_order.artikal_id
    db_order.user_id = updated_order.user_id
    db.commit()
    db.refresh(db_order)

    # Update the cache
    redis_client.delete("orders")
    redis_client.set(f"order:{order_id}", json.dumps({"id": db_order.id, "user_id": db_order.user_id}))
    return db_order

@app.delete("/orders/{order_id}", tags=["Users"])
def delete_order(order_id: int, db: Session = Depends(get_db)):
    db_order = db.query(Order).filter(Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    db.delete(db_order)
    db.commit()

    # Remove from cache
    redis_client.delete("orders")
    redis_client.delete(f"order:{order_id}")
    return

## Recenzije
@app.post("/recenzije/", response_model=RecenzijaResponse, tags=["Users"])
def create_recenzija(recenzija: RecenzijaCreate, db: Session = Depends(get_db)):
    db_recenzija = Recenzija(rating=recenzija.rating)
    db.add(db_recenzija)
    db.commit()
    db.refresh(db_recenzija)

    # Cache the new recenzija
    redis_client.delete("recenzije")
    redis_client.set(f"recenzija:{db_recenzija.id}", json.dumps({"id": db_recenzija.id, "rating": db_recenzija.rating}))
    return db_recenzija

@app.get("/recenzije/", response_model=List[RecenzijaResponse], tags=["Users"])
def list_recenzije(db: Session = Depends(get_db)):
    cached_recenzije = redis_client.get("recenzije")
    if cached_recenzije:
        return json.loads(cached_recenzije)

    recenzije = db.query(Recenzija).all()
    redis_client.set("recenzije", json.dumps([{"id": recenzija.id, "rating": recenzija.rating} for recenzija in recenzije]))
    return recenzije

@app.put("/recenzije/{recenzija_id}", response_model=RecenzijaResponse, tags=["Users"])
def update_recenzija(recenzija_id: int, updated_recenzija: RecenzijaCreate, db: Session = Depends(get_db)):
    db_recenzija = db.query(Recenzija).filter(Recenzija.id == recenzija_id).first()
    if not db_recenzija:
        raise HTTPException(status_code=404, detail="Recenzija not found")

    db_recenzija.rating = updated_recenzija.rating
    db.commit()
    db.refresh(db_recenzija)

    # Update the cache
    redis_client.delete("recenzije")
    redis_client.set(f"recenzija:{recenzija_id}", json.dumps({"id": db_recenzija.id, "rating": db_recenzija.rating}))
    return db_recenzija

@app.delete("/recenzije/{recenzija_id}", tags=["Users"])
def delete_recenzija(recenzija_id: int, db: Session = Depends(get_db)):
    db_recenzija = db.query(Recenzija).filter(Recenzija.id == recenzija_id).first()
    if not db_recenzija:
        raise HTTPException(status_code=404, detail="Recenzija not found")
    db.delete(db_recenzija)
    db.commit()

    # Remove from cache
    redis_client.delete("recenzije")
    redis_client.delete(f"recenzija:{recenzija_id}")
    return